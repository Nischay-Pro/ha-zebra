"""Zebra client for SGD settings and raw ZPL print jobs over local TCP."""

from __future__ import annotations

import asyncio


class ZebraConnectionError(Exception):
    """The printer could not be contacted or did not confirm a setting."""



class ZebraClient:
    """Exchange SGD commands and raw ZPL print jobs with a Zebra printer."""

    def __init__(self, host: str, port: int = 9100) -> None:
        self.host = host
        self.port = port

    async def _send(self, command: str, *, expect_reply: bool) -> str | None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=4
            )
            try:
                writer.write((command + "\r\n").encode("ascii"))
                await asyncio.wait_for(writer.drain(), timeout=4)
                if not expect_reply:
                    return None
                # Zebra documents a single getvar value as a quoted response.
                # Read through the closing quote rather than assuming one TCP
                # read contains the whole response: TCP may split it anywhere.
                first = await asyncio.wait_for(reader.readexactly(1), timeout=4)
                if first == b"?":
                    return "?"
                if first != b'"':
                    raise ZebraConnectionError(
                        "Printer returned an SGD response without the expected "
                        "opening quote"
                    )
                raw = await asyncio.wait_for(reader.readuntil(b'"'), timeout=4)
                return raw[:-1].decode("ascii", errors="replace").strip()
            finally:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=1)
                except (OSError, asyncio.TimeoutError):
                    pass
        except ZebraConnectionError:
            raise
        except asyncio.IncompleteReadError as err:
            raise ZebraConnectionError(
                "Printer closed the connection before completing its SGD response"
            ) from err
        except asyncio.LimitOverrunError as err:
            raise ZebraConnectionError(
                "Printer returned an oversized SGD response"
            ) from err
        except (OSError, asyncio.TimeoutError) as err:
            raise ZebraConnectionError(f"Could not communicate with printer: {err}") from err

    async def send_print_job(self, zpl: str) -> None:
        """Send one raw ZPL payload without retrying or expecting a printer reply."""
        payload = zpl.encode("utf-8")

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=4
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise ZebraConnectionError(
                f"Could not connect to printer at {self.host}:{self.port}: {err}"
            ) from err

        try:
            writer.write(payload)
            await asyncio.wait_for(writer.drain(), timeout=4)
        except (OSError, asyncio.TimeoutError) as err:
            raise ZebraConnectionError(
                "Could not confirm print transmission. The job may have reached "
                "the printer and was not retried."
            ) from err
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1)
            except (OSError, asyncio.TimeoutError):
                # Once drain succeeds, a close error does not establish whether
                # the printer printed the job. Never turn it into a retry.
                pass

    async def send_sgd_command(self, command: str) -> None:
        """Send one SGD command without waiting for a response."""
        await self._send(command, expect_reply=False)

    async def get(self, variable: str) -> str | None:
        """Read an SGD variable, returning None when unsupported."""
        result = await self._send(f'! U1 getvar "{variable}"', expect_reply=True)
        return None if result in (None, "?", "") else result

    async def set(self, variable: str, value: str) -> None:
        """Set a fixed SGD variable and verify the printer accepted it."""
        await self._send(f'! U1 setvar "{variable}" "{value}"', expect_reply=False)
        for _ in range(3):
            await asyncio.sleep(0.25)
            if await self.get(variable) == value:
                return
        raise ZebraConnectionError(f"Printer did not confirm {variable}")

    async def calibrate_media(self) -> None:
        """Run the printer's media and ribbon sensor calibration."""
        await self._send('! U1 do "ezpl.manual_calibration" ""', expect_reply=False)
