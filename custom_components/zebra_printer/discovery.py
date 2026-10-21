"""Discover Zebra printers using Zebra's UDP network discovery."""

from __future__ import annotations

import asyncio
from ipaddress import IPv4Interface, ip_interface

from homeassistant.components import network
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

DISCOVERY_PORT = 4201
# The request and reply prefix are the signatures used by Link-OS discovery.
_DISCOVERY_REQUEST = bytes.fromhex("2e2c3a010000")
_DISCOVERY_RESPONSE_PREFIX = bytes.fromhex("3a2c2e03")
_DISCOVERY_ATTEMPTS = 9
_DISCOVERY_INTERVAL = 0.1
_DISCOVERY_TIMEOUT = 1.5


class _ZebraDiscoveryProtocol(asyncio.DatagramProtocol):
    """Collect valid Zebra discovery replies."""

    def __init__(self) -> None:
        """Initialize the discovery response set."""
        self.printers: set[str] = set()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Record the sender of a Zebra discovery response."""
        if data.startswith(_DISCOVERY_RESPONSE_PREFIX):
            self.printers.add(addr[0])


async def async_discover_printers(hass: HomeAssistant) -> list[str]:
    """Broadcast Zebra discovery probes on enabled Home Assistant networks."""
    try:
        adapters = await network.async_get_adapters(hass)
    except (HomeAssistantError, OSError):
        return []

    interfaces: set[tuple[str, str]] = set()
    for adapter in adapters:
        if not adapter.get("enabled"):
            continue
        for address_info in adapter.get("ipv4", []):
            try:
                interface = ip_interface(
                    f"{address_info['address']}/{address_info['network_prefix']}"
                )
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not isinstance(interface, IPv4Interface)
                or interface.network.prefixlen >= 31
                or interface.ip.is_loopback
                or interface.ip.is_link_local
                or interface.ip.is_multicast
            ):
                continue
            interfaces.add(
                (str(interface.ip), str(interface.network.broadcast_address))
            )

    if not interfaces:
        return []

    loop = asyncio.get_running_loop()
    transports: list[tuple[asyncio.DatagramTransport, str]] = []
    protocols: list[_ZebraDiscoveryProtocol] = []
    try:
        for local_address, broadcast_address in sorted(interfaces):
            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    _ZebraDiscoveryProtocol,
                    local_addr=(local_address, 0),
                    allow_broadcast=True,
                )
            except OSError:
                continue
            transports.append((transport, broadcast_address))
            protocols.append(protocol)

        if not transports:
            return []

        for attempt in range(_DISCOVERY_ATTEMPTS):
            for transport, broadcast_address in transports:
                try:
                    transport.sendto(
                        _DISCOVERY_REQUEST,
                        (broadcast_address, DISCOVERY_PORT),
                    )
                except OSError:
                    continue
            if attempt < _DISCOVERY_ATTEMPTS - 1:
                await asyncio.sleep(_DISCOVERY_INTERVAL)

        await asyncio.sleep(_DISCOVERY_TIMEOUT)
        return sorted(
            {host for protocol in protocols for host in protocol.printers}
        )
    finally:
        for transport, _ in transports:
            transport.close()
