"""Binary status entities for Zebra printer conditions."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import ZebraEntity

SENSORS = {
    "needs_attention": BinarySensorDeviceClass.PROBLEM,
    "media_out": BinarySensorDeviceClass.PROBLEM,
    "ribbon_out": BinarySensorDeviceClass.PROBLEM,
    "head_open": BinarySensorDeviceClass.PROBLEM,
    "paused": None,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create binary sensors for current printer status flags."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ZebraStatusBinarySensor(coordinator, entry, key) for key in SENSORS
    )


class ZebraStatusBinarySensor(ZebraEntity, BinarySensorEntity):
    """Expose one decoded Zebra status condition as an on/off entity."""

    def __init__(self, coordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator, entry, key)
        self.key = key
        self._attr_translation_key = key
        self._attr_device_class = SENSORS[key]

    @property
    def available(self) -> bool:
        """Keep status entities unavailable when the status response is invalid."""
        return super().available and self.coordinator.data.get("operating_status") is not None

    @property
    def is_on(self) -> bool:
        """Return whether the selected printer condition is active."""
        data = self.coordinator.data
        if self.key == "paused":
            return data.get("status_paused") is True

        errors = data.get("status_errors")
        warnings = data.get("status_warnings")
        if not isinstance(errors, list) or not isinstance(warnings, list):
            return False
        if self.key == "needs_attention":
            return bool(errors or warnings)

        condition = {
            "media_out": "Media out",
            "ribbon_out": "Ribbon out",
            "head_open": "Head open",
        }[self.key]
        return condition in errors
