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


class ZebraDiscoveryError(HomeAssistantError):
    """Base error with a translation key for discovery setup feedback."""

    translation_key = "discovery_transport_error"


class ZebraDiscoveryNetworkError(ZebraDiscoveryError):
    """Home Assistant could not enumerate network adapters."""

    translation_key = "discovery_network_error"


class ZebraDiscoveryNoInterfacesError(ZebraDiscoveryError):
    """Home Assistant has no eligible IPv4 broadcast interface."""

    translation_key = "discovery_no_interfaces"


class ZebraDiscoveryTransportError(ZebraDiscoveryError):
    """Home Assistant could not bind or send discovery probes."""

    translation_key = "discovery_transport_error"


class _ZebraDiscoveryProtocol(asyncio.DatagramProtocol):
    """Collect valid Zebra discovery replies."""

    def __init__(self) -> None:
        """Initialize the discovery response set."""
        self.printers: set[str] = set()
        self.transport_errors: list[Exception] = []

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Record the sender of a Zebra discovery response."""
        if data.startswith(_DISCOVERY_RESPONSE_PREFIX):
            self.printers.add(addr[0])

    def error_received(self, exc: Exception) -> None:
        """Record asynchronous UDP errors reported by the operating system."""
        self.transport_errors.append(exc)


async def async_discover_printers(hass: HomeAssistant) -> list[str]:
    """Broadcast Zebra discovery probes on enabled Home Assistant networks."""
    try:
        adapters = await network.async_get_adapters(hass)
    except (HomeAssistantError, OSError) as err:
        raise ZebraDiscoveryNetworkError(
            "Home Assistant could not read available network adapters"
        ) from err

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
        raise ZebraDiscoveryNoInterfacesError(
            "No enabled IPv4 broadcast interface is available for Zebra discovery"
        )

    loop = asyncio.get_running_loop()
    transports: list[tuple[asyncio.DatagramTransport, str]] = []
    protocols: list[_ZebraDiscoveryProtocol] = []
    bind_errors: list[OSError] = []
    try:
        for local_address, broadcast_address in sorted(interfaces):
            try:
                transport, protocol = await loop.create_datagram_endpoint(
                    _ZebraDiscoveryProtocol,
                    local_addr=(local_address, 0),
                    allow_broadcast=True,
                )
            except OSError as err:
                bind_errors.append(err)
                continue
            transports.append((transport, broadcast_address))
            protocols.append(protocol)

        if not transports:
            raise ZebraDiscoveryTransportError(
                "Home Assistant could not bind a UDP socket on any eligible interface"
            ) from (bind_errors[-1] if bind_errors else None)

        send_errors: list[OSError] = []
        sent_on_interface = False
        for attempt in range(_DISCOVERY_ATTEMPTS):
            for transport, broadcast_address in transports:
                try:
                    transport.sendto(
                        _DISCOVERY_REQUEST,
                        (broadcast_address, DISCOVERY_PORT),
                    )
                    sent_on_interface = True
                except OSError as err:
                    send_errors.append(err)
            if attempt < _DISCOVERY_ATTEMPTS - 1:
                await asyncio.sleep(_DISCOVERY_INTERVAL)

        await asyncio.sleep(_DISCOVERY_TIMEOUT)
        printers = sorted(
            {host for protocol in protocols for host in protocol.printers}
        )
        if printers:
            return printers
        protocol_errors = [
            error
            for protocol in protocols
            for error in protocol.transport_errors
        ]
        transport_error = (
            protocol_errors[-1]
            if protocol_errors
            else send_errors[-1]
            if send_errors
            else bind_errors[-1]
            if bind_errors
            else None
        )
        if not sent_on_interface:
            raise ZebraDiscoveryTransportError(
                "Home Assistant could not send UDP discovery probes"
            ) from transport_error
        if bind_errors or send_errors or protocol_errors:
            raise ZebraDiscoveryTransportError(
                "Zebra discovery could not use every eligible network interface"
            ) from transport_error
        return []
    finally:
        for transport, _ in transports:
            transport.close()
