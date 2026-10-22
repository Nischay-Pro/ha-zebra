"""Test the SGD client against a local no-newline printer stub."""

import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch


API_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "zebra_printer" / "api.py"
SPEC = importlib.util.spec_from_file_location("zebra_api_under_test", API_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ZebraClient = MODULE.ZebraClient


class ZebraClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.values = {"ezpl.print_method": "direct thermal"}
        self.requests = []
        self.accept_writes = True

        async def handle(reader, writer):
            command = (await reader.readline()).decode("ascii").strip()
            self.requests.append(command)
            parts = command.split('"')
            if command.startswith("! U1 getvar"):
                value = self.values.get(parts[1], "?")
                if value == "__empty_response__":
                    writer.close()
                    await writer.wait_closed()
                    return
                writer.write(f'"{value}"'.encode("ascii"))
                await writer.drain()
            elif command.startswith("! U1 setvar"):
                if self.accept_writes:
                    self.values[parts[1]] = parts[3]
            writer.close()
            await writer.wait_closed()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.client = ZebraClient("127.0.0.1", port)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_read_and_verified_write(self):
        self.assertEqual(await self.client.get("ezpl.print_method"), "direct thermal")
        self.assertIsNone(await self.client.get("unsupported"))
        await self.client.set("ezpl.print_method", "thermal transfer")
        self.assertEqual(await self.client.get("ezpl.print_method"), "thermal transfer")
        self.assertEqual(
            self.requests[:2],
            [
                '! U1 getvar "ezpl.print_method"',
                '! U1 getvar "unsupported"',
            ],
        )
        self.assertIn(
            '! U1 setvar "ezpl.print_method" "thermal transfer"', self.requests
        )

    async def test_empty_reply_is_reported_as_connection_error(self):
        self.values["empty"] = "__empty_response__"
        with self.assertRaises(MODULE.ZebraConnectionError):
            await self.client.get("empty")

    async def test_write_must_be_confirmed_by_readback(self):
        self.accept_writes = False
        with self.assertRaisesRegex(MODULE.ZebraConnectionError, "did not confirm"):
            await self.client.set("ezpl.print_method", "thermal transfer")
        self.assertEqual(
            self.requests.count('! U1 getvar "ezpl.print_method"'), 3
        )


if __name__ == "__main__":
    unittest.main()

class _FakeReader:
    def __init__(self, *, first=b'"', rest=b'value"', read_error=None, rest_error=None):
        self.first = first
        self.rest = rest
        self.read_error = read_error
        self.rest_error = rest_error

    async def readexactly(self, _count):
        if self.read_error:
            raise self.read_error
        return self.first

    async def readuntil(self, _separator):
        if self.rest_error:
            raise self.rest_error
        return self.rest


class _FakeWriter:
    def __init__(self, *, drain_error=None, close_error=None):
        self.drain_error = drain_error
        self.close_error = close_error
        self.writes = []
        self.closed = False

    def write(self, payload):
        self.writes.append(payload)

    async def drain(self):
        if self.drain_error:
            raise self.drain_error

    def close(self):
        self.closed = True

    async def wait_closed(self):
        if self.close_error:
            raise self.close_error


class ZebraClientFailureCoverageTest(unittest.IsolatedAsyncioTestCase):
    async def test_sgd_response_shapes_and_read_errors(self):
        client = ZebraClient("printer", 9100)
        writer = _FakeWriter(close_error=OSError("close"))
        with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(), writer))):
            self.assertEqual(await client._send("get", expect_reply=True), "value")
        self.assertTrue(writer.closed)

        with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(first=b"?"), _FakeWriter()))):
            self.assertEqual(await client.get("unknown"), None)
        with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(first=b"x"), _FakeWriter()))):
            with self.assertRaisesRegex(MODULE.ZebraConnectionError, "opening quote"):
                await client.get("broken")
        incomplete = asyncio.IncompleteReadError(partial=b"", expected=1)
        with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(read_error=incomplete), _FakeWriter()))):
            with self.assertRaisesRegex(MODULE.ZebraConnectionError, "closed the connection"):
                await client.get("truncated")
        overrun = asyncio.LimitOverrunError("response too long", 1)
        with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(rest_error=overrun), _FakeWriter()))):
            with self.assertRaisesRegex(MODULE.ZebraConnectionError, "oversized"):
                await client.get("large")
        for failure in (OSError("offline"), asyncio.TimeoutError()):
            with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(side_effect=failure)):
                with self.assertRaises(MODULE.ZebraConnectionError):
                    await client.get("offline")

    async def test_one_way_commands_and_print_job_failures_close_stream(self):
        client = ZebraClient("printer", 9100)
        for command in (
            '! U1 do "ezpl.manual_calibration" ""',
            "! U1 do test",
        ):
            writer = _FakeWriter()
            with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(), writer))):
                if "calibration" in command:
                    await client.calibrate_media()
                else:
                    await client.send_sgd_command(command)
            self.assertEqual(writer.writes, [(command + "\r\n").encode("ascii")])
            self.assertTrue(writer.closed)

        writer = _FakeWriter(close_error=asyncio.TimeoutError())
        with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(), writer))):
            await client.send_print_job("^XAé^XZ")
        self.assertEqual(writer.writes, ["^XAé^XZ".encode("utf-8")])
        self.assertTrue(writer.closed)

        for failure in (OSError("offline"), asyncio.TimeoutError()):
            with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(side_effect=failure)):
                with self.assertRaisesRegex(MODULE.ZebraConnectionError, "Could not connect"):
                    await client.send_print_job("^XA^XZ")
        for failure in (OSError("drain"), asyncio.TimeoutError()):
            writer = _FakeWriter(drain_error=failure)
            with patch.object(MODULE.asyncio, "open_connection", new=AsyncMock(return_value=(_FakeReader(), writer))):
                with self.assertRaisesRegex(MODULE.ZebraConnectionError, "was not retried"):
                    await client.send_print_job("^XA^XZ")
            self.assertTrue(writer.closed)
