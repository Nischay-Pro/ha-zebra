"""Zebra ZD420 sensors and controls."""

from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ZebraClient, ZebraConnectionError
from .alerts import (
    ZebraAlertConfiguration,
    async_configure_printer_alerts,
    async_register_webhook,
    async_remove_printer_alerts,
    async_unregister_webhook,
    configuration_from_options,
)
from .const import (
    DOMAIN,
    POLL_SECONDS,
    RIBBON_CARTRIDGE_FEATURE,
    RIBBON_INSERTED_VARIABLE,
    RIBBON_LOW_WARNING_CHOICES,
    RIBBON_REMAINING_VARIABLE,
    RIBBON_WARNING_VARIABLE,
    is_ribbon_cartridge_capable,
    parse_ribbon_cartridge_inserted,
    parse_operating_status,
)
from .identity import async_migrate_config_entry_identity, config_entry_unique_id
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PRINTHEAD_USAGE_VARIABLE = "device.printhead.odometer"
PRINT_SETTINGS_VARIABLES = {
    "print_tone": "print.tone",
    "print_speed": "media.speed",
    "media_type_raw": "ezpl.media_type",
    "resolution_dpi": "head.resolution.in_dpi",
}
MEDIA_TYPE_VALUES_BY_PRINTER_VALUE = {
    "continuous": "continuous",
    "gap/notch": "gap/notch",
    "gap/web": "gap/notch",
    "mark": "mark",
    "mark/notch": "mark",
}

VARIABLES = {
    "model": "device.product_name",
    "total_labels": "odometer.total_label_count",
    "resettable_labels_1": "odometer.user_label_count1",
    "resettable_labels_2": "odometer.user_label_count2",
    "total_print_length": "odometer.total_print_length",
    "firmware": "appl.name",
    "print_method": "ezpl.print_method",
    "ribbon_cartridge_status": RIBBON_CARTRIDGE_FEATURE,
    "paper_supply": "sensor.paper_supply",
    "printhead_temperature": "sensor.head.temp_celsius",
    "system_status": "zpl.system_status",
}


class ZebraCoordinator(DataUpdateCoordinator[dict[str, object]]):
    """Poll the printer without modifying its settings."""

    def __init__(self, hass: HomeAssistant, client: ZebraClient) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=POLL_SECONDS)
        )
        self.client = client
        self.last_communication_error: str | None = None
        self.alert_configuration: ZebraAlertConfiguration | None = None
        self.file_transfer_lock = asyncio.Lock()

    async def _async_read_variable(
        self,
        name: str,
        variable: str,
        optional_read_errors: list[str],
        *,
        required: bool = False,
    ) -> str | None:
        """Read one variable, isolating failures for optional readings."""
        try:
            value = await self.client.get(variable)
        except ZebraConnectionError:
            if required:
                self.last_communication_error = (
                    f"Could not read required printer value: {name}"
                )
                raise
            optional_read_errors.append(name)
            return None

        if required and value is None:
            message = f"Required printer value {name} is unavailable"
            self.last_communication_error = message
            raise ZebraConnectionError(message)
        return value

    async def _async_update_data(self) -> dict[str, object]:
        optional_read_errors: list[str] = []
        try:
            data: dict[str, object] = {}
            required_names = {"total_labels", "print_method"}
            for name, variable in VARIABLES.items():
                data[name] = await self._async_read_variable(
                    name,
                    variable,
                    optional_read_errors,
                    required=name in required_names,
                )

            # These readings vary by firmware and installed printer options.
            data["printhead_usage"] = await self._async_read_variable(
                "printhead_usage", PRINTHEAD_USAGE_VARIABLE, optional_read_errors
            )
            for name, variable in PRINT_SETTINGS_VARIABLES.items():
                data[name] = await self._async_read_variable(
                    name, variable, optional_read_errors
                )

            ribbon_status = str(data["ribbon_cartridge_status"] or "").strip().casefold()
            data["ribbon_cartridge_status"] = ribbon_status or None
            data["ribbon_cartridge_capable"] = is_ribbon_cartridge_capable(ribbon_status)
            data["ribbon_inserted"] = None
            data["ribbon_remaining"] = None
            data["ribbon_low_warning"] = None
            if data["ribbon_cartridge_capable"]:
                raw_warning = await self._async_read_variable(
                    "ribbon_low_warning",
                    RIBBON_WARNING_VARIABLE,
                    optional_read_errors,
                )
                warning_value = str(raw_warning or "").strip().casefold()
                if warning_value in set(RIBBON_LOW_WARNING_CHOICES.values()):
                    data["ribbon_low_warning"] = warning_value

                raw_inserted = await self._async_read_variable(
                    "ribbon_inserted",
                    RIBBON_INSERTED_VARIABLE,
                    optional_read_errors,
                )
                data["ribbon_inserted"] = parse_ribbon_cartridge_inserted(
                    raw_inserted
                )

                if data["ribbon_inserted"] is True:
                    raw_remaining = await self._async_read_variable(
                        "ribbon_remaining",
                        RIBBON_REMAINING_VARIABLE,
                        optional_read_errors,
                    )
                    try:
                        remaining = float(str(raw_remaining))
                    except (TypeError, ValueError):
                        remaining = None
                    if (
                        remaining is not None
                        and math.isfinite(remaining)
                        and 0 <= remaining <= 74
                    ):
                        data["ribbon_remaining"] = remaining
        except ZebraConnectionError as err:
            raise UpdateFailed(str(err)) from err

        for name in ("total_labels", "resettable_labels_1", "resettable_labels_2"):
            value = data[name]
            try:
                parsed_value = int(str(value).strip())
            except (TypeError, ValueError):
                parsed_value = None
            data[name] = (
                parsed_value
                if parsed_value is not None and parsed_value >= 0
                else None
            )
            if name == "total_labels" and data[name] is None:
                raise UpdateFailed("Printer returned an invalid lifetime label counter")
        length = data["total_print_length"]
        match = re.match(r"(\d+) INCHES", str(length or ""))
        data["total_print_length"] = int(match.group(1)) if match else None
        raw_printhead_usage = data["printhead_usage"]
        try:
            printhead_usage = int(str(raw_printhead_usage).strip())
        except (TypeError, ValueError):
            printhead_usage = None
        data["printhead_usage"] = (
            printhead_usage
            if printhead_usage is not None and printhead_usage >= 0
            else None
        )

        # Zebra documents darkness as 0.0-30.0 in 0.1 increments.
        try:
            print_tone = float(str(data["print_tone"]).strip())
        except (TypeError, ValueError):
            print_tone = None
        data["print_tone"] = (
            print_tone
            if print_tone is not None and math.isfinite(print_tone) and 0 <= print_tone <= 30
            else None
        )

        # ZD420 print speed limits depend on the printer-reported printhead DPI.
        try:
            resolution_dpi = int(str(data["resolution_dpi"]).strip())
        except (TypeError, ValueError):
            resolution_dpi = None
        max_speed = {203: 6, 300: 4}.get(resolution_dpi)
        data["print_speed_max"] = max_speed
        try:
            print_speed_raw = float(str(data["print_speed"]).strip())
            print_speed = int(print_speed_raw) if print_speed_raw.is_integer() else None
        except (TypeError, ValueError):
            print_speed = None
        data["print_speed"] = (
            print_speed
            if max_speed is not None
            and print_speed is not None
            and 2 <= print_speed <= max_speed
            else None
        )

        raw_media_type = str(data["media_type_raw"] or "").strip().strip('"').casefold()
        data["media_type"] = MEDIA_TYPE_VALUES_BY_PRINTER_VALUE.get(raw_media_type)
        temperature = data["printhead_temperature"]
        try:
            temperature_value = float(str(temperature))
        except (TypeError, ValueError):
            temperature_value = None
        data["printhead_temperature"] = (
            temperature_value
            if temperature_value is not None and math.isfinite(temperature_value)
            else None
        )
        status = parse_operating_status(
            data["system_status"] if isinstance(data["system_status"], str) else None
        )
        data["operating_status"] = status.state if status else None
        data["status_paused"] = status.paused if status else None
        data["status_errors"] = list(status.errors) if status else None
        data["status_warnings"] = list(status.warnings) if status else None
        data["optional_read_errors"] = optional_read_errors
        self.last_communication_error = None
        return data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register service actions even when no printer entry is loaded."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize one Zebra printer."""
    client = ZebraClient(entry.data["host"], entry.data["port"])
    coordinator = ZebraCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    try:
        printer_unique_id = await client.get("device.unique_id")
    except ZebraConnectionError:
        printer_unique_id = None
        _LOGGER.debug(
            "Could not read stable printer identity for config entry %s",
            entry.entry_id,
        )
    if printer_unique_id:
        async_migrate_config_entry_identity(
            hass, entry, config_entry_unique_id(printer_unique_id.strip())
        )
    alert_configuration = configuration_from_options(entry.options)
    if alert_configuration is not None:
        # Register the local-only endpoint before asking the printer to send
        # anything to it. The URL and generated ID are never logged.
        await async_register_webhook(
            hass,
            entry,
            alert_configuration,
            expected_printer_unique_id=printer_unique_id,
        )
        coordinator.alert_configuration = alert_configuration
        try:
            await async_configure_printer_alerts(client, alert_configuration)
        except ZebraConnectionError as err:
            _LOGGER.warning(
                "Could not configure printer alert delivery for entry %s: %s",
                entry.entry_id,
                err,
            )
        except ValueError:
            _LOGGER.warning(
                "Printer alert delivery is unavailable for entry %s",
                entry.entry_id,
            )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Zebra printer."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        alert_configuration = (
            coordinator.alert_configuration
            if coordinator is not None
            else None
        )
        if isinstance(alert_configuration, ZebraAlertConfiguration):
            async_unregister_webhook(hass, alert_configuration)
            try:
                await async_remove_printer_alerts(
                    coordinator.client, alert_configuration
                )
            except ZebraConnectionError as err:
                _LOGGER.warning(
                    "Could not remove printer alert delivery for entry %s: %s",
                    entry.entry_id,
                    err,
                )
        return True
    return False


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove printer alert rules when an entry is deleted while unloaded."""
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        return
    alert_configuration = configuration_from_options(entry.options)
    if alert_configuration is None:
        return
    async_unregister_webhook(hass, alert_configuration)
    client = ZebraClient(entry.data["host"], entry.data["port"])
    try:
        await async_remove_printer_alerts(client, alert_configuration)
    except ZebraConnectionError as err:
        _LOGGER.warning(
            "Could not remove printer alert delivery for deleted entry %s: %s",
            entry.entry_id,
            err,
        )


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload for connection or alert changes; refresh for other options."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return

    if (
        entry.data.get("host") != coordinator.client.host
        or entry.data.get("port") != coordinator.client.port
        or configuration_from_options(entry.options) != coordinator.alert_configuration
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        return

    await coordinator.async_request_refresh()
