"""Numeric print configuration controls for Zebra printers."""

from __future__ import annotations

import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ZebraConnectionError
from .const import DOMAIN
from .entity import ZebraEntity

PRINT_TONE_VARIABLE = "print.tone"
PRINT_SPEED_VARIABLE = "media.speed"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create numeric controls and let availability follow printer readings."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        (
            ZebraPrintTone(coordinator, entry, "print_tone"),
            ZebraPrintSpeed(coordinator, entry, "print_speed"),
        )
    )


class ZebraPrintTone(ZebraEntity, NumberEntity):
    """Set print darkness in Zebra's documented 0.0-30.0 range."""

    _attr_translation_key = "print_tone"
    _attr_icon = "mdi:brightness-6"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0.0
    _attr_native_max_value = 30.0
    _attr_native_step = 0.1
    _attr_suggested_display_precision = 1

    @property
    def available(self) -> bool:
        """Mark this optional control unavailable if its SGD read fails."""
        return super().available and self.coordinator.data.get("print_tone") is not None

    @property
    def native_value(self) -> float | None:
        """Return the darkness currently read from the printer."""
        value = self.coordinator.data.get("print_tone")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set darkness and confirm the printer stored it."""
        if (
            not math.isfinite(value)
            or not 0 <= value <= 30
            or not math.isclose(value * 10, round(value * 10), abs_tol=1e-6)
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_print_configuration_value",
            )
        try:
            await self.coordinator.client.set(PRINT_TONE_VARIABLE, f"{value:.1f}")
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="print_configuration_change_failed",
            ) from err
        await self.coordinator.async_request_refresh()


class ZebraPrintSpeed(ZebraEntity, NumberEntity):
    """Set print speed within the ZD420's resolution-specific limits."""

    _attr_translation_key = "print_speed"
    _attr_icon = "mdi:speedometer"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 2.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfSpeed.INCHES_PER_SECOND

    @property
    def available(self) -> bool:
        """Require a known print speed and supported printhead resolution."""
        return (
            super().available
            and self.coordinator.data.get("print_speed") is not None
            and self.coordinator.data.get("print_speed_max") is not None
        )

    @property
    def native_max_value(self) -> float:
        """Return the ZD420 limit for the printer-reported DPI."""
        return float(self.coordinator.data.get("print_speed_max") or 2)

    @property
    def native_value(self) -> float | None:
        """Return the current printer speed in inches per second."""
        value = self.coordinator.data.get("print_speed")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set and verify a speed accepted for this printhead resolution."""
        max_speed = self.coordinator.data.get("print_speed_max")
        if (
            not math.isfinite(value)
            or max_speed is None
            or not value.is_integer()
            or not 2 <= value <= max_speed
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_print_configuration_value",
            )
        try:
            await self.coordinator.client.set(PRINT_SPEED_VARIABLE, str(int(value)))
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="print_configuration_change_failed",
            ) from err
        await self.coordinator.async_request_refresh()