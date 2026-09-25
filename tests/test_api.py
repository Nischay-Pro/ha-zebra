"""Test the SGD client against a local no-newline printer stub."""

import asyncio
import importlib.util
from pathlib import Path
import unittest


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
