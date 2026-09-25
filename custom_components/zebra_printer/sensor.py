"""Zebra printer statistics."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import ZebraEntity

SENSORS = {
    "operating_status": ("mdi:printer-check", None, None),
    "total_labels": ("mdi:counter", "labels", SensorStateClass.TOTAL_INCREASING),
    "resettable_labels_1": ("mdi:counter", "labels", None),
    "resettable_labels_2": ("mdi:counter", "labels", None),
    "total_print_length": ("mdi:ruler", "in", SensorStateClass.TOTAL_INCREASING),
    "firmware": ("mdi:chip", None, None),
    "printhead_temperature": (
        "mdi:thermometer",
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
    ),
    "ribbon_inserted": ("mdi:ribbon", None, None),
    "paper_supply": ("mdi:receipt-text", None, None),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the printer's live sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(ZebraSensor(coordinator, entry, key) for key in SENSORS)


class ZebraSensor(ZebraEntity, SensorEntity):
    """One Zebra setting or odometer value."""

    def __init__(self, coordinator, entry, key: str) -> None:
        super().__init__(coordinator, entry, key)
        self.key = key
        icon, unit, state_class = SENSORS[key]
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        if key == "printhead_temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
        if key == "firmware":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the latest polled value."""
        value = self.coordinator.data.get(self.key)
        if self.key == "ribbon_inserted":
            return "Loaded" if value else "Not loaded"
        return value

    @property
    def extra_state_attributes(self):
        """Expose simultaneous printer conditions on the status sensor."""
        if self.key != "operating_status":
            return None
        return {
            "paused": self.coordinator.data.get("status_paused"),
            "errors": self.coordinator.data.get("status_errors", []),
            "warnings": self.coordinator.data.get("status_warnings", []),
        }
