"""Zebra ZD420 sensors and controls."""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ZebraClient, ZebraConnectionError
from .const import DOMAIN, POLL_SECONDS, parse_operating_status

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.SELECT, Platform.BUTTON]

VARIABLES = {
    "model": "device.product_name",
    "total_labels": "odometer.total_label_count",
    "resettable_labels_1": "odometer.user_label_count1",
    "resettable_labels_2": "odometer.user_label_count2",
    "total_print_length": "odometer.total_print_length",
    "firmware": "appl.name",
    "print_method": "ezpl.print_method",
    "ribbon_inserted": "ribbon.cartridge.inserted",
    "paper_supply": "sensor.paper_supply",
    "printhead_temperature": "sensor.head.temp_celsius",
    "system_status": "zpl.system_status",
}


class ZebraCoordinator(DataUpdateCoordinator[dict[str, str | int | float | bool | None]]):
    """Poll the printer without modifying its settings."""

    def __init__(self, hass: HomeAssistant, client: ZebraClient) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=POLL_SECONDS)
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, str | int | float | bool | None]:
        try:
            data = {}
            for name, variable in VARIABLES.items():
                data[name] = await self.client.get(variable)
            if data["total_labels"] is None or data["print_method"] is None:
                raise ZebraConnectionError("Required Zebra counters/settings unavailable")
        except ZebraConnectionError as err:
            raise UpdateFailed(str(err)) from err

        for name in ("total_labels", "resettable_labels_1", "resettable_labels_2"):
            value = data[name]
            data[name] = int(value) if value and str(value).isdigit() else None
        length = data["total_print_length"]
        match = re.match(r"(\d+) INCHES", str(length or ""))
        data["total_print_length"] = int(match.group(1)) if match else None
        temperature = data["printhead_temperature"]
        try:
            data["printhead_temperature"] = float(temperature) if temperature else None
        except ValueError:
            data["printhead_temperature"] = None
        data["ribbon_inserted"] = data["ribbon_inserted"] == "yes"
        status = parse_operating_status(data["system_status"])
        data["operating_status"] = status.state if status else None
        data["status_paused"] = status.paused if status else None
        data["status_errors"] = list(status.errors) if status else []
        data["status_warnings"] = list(status.warnings) if status else []
        return data


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize one Zebra printer."""
    client = ZebraClient(entry.data["host"], entry.data["port"])
    coordinator = ZebraCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Zebra printer."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
