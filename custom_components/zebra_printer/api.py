"""Small, read/write Zebra SGD client for a local raw-print socket."""

from __future__ import annotations

import asyncio


class ZebraConnectionError(Exception):
    """The printer could not be contacted or did not confirm a setting."""


class ZebraClient:
    """Exchange one SGD command per TCP connection with a Zebra printer."""

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
                # SGD replies from this ZD420 are quoted but have no newline.
                raw = await asyncio.wait_for(reader.read(512), timeout=4)
                if not raw:
                    raise ZebraConnectionError("Printer returned an empty response")
                return raw.decode("ascii", errors="replace").strip().strip('"')
            finally:
                writer.close()
                await writer.wait_closed()
        except (OSError, asyncio.TimeoutError) as err:
            raise ZebraConnectionError(f"Could not communicate with printer: {err}") from err

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
