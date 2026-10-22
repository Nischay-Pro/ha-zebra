"""Zebra printer statistics."""

from __future__ import annotations

import math

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_MEDIA_ROLL_BASELINE_INCHES,
    CONF_MEDIA_ROLL_LENGTH_INCHES,
    CONF_MEDIA_ROLL_REMAINING_INCHES,
    DOMAIN,
)
from .entity import ZebraEntity

SENSORS = {
    "operating_status": ("mdi:printer-check", None, None),
    "total_labels": ("mdi:counter", "labels", SensorStateClass.TOTAL_INCREASING),
    "resettable_labels_1": ("mdi:counter", "labels", None),
    "resettable_labels_2": ("mdi:counter", "labels", None),
    "total_print_length": ("mdi:ruler", "in", SensorStateClass.TOTAL_INCREASING),
    "estimated_media_remaining": (
        "mdi:chart-donut",
        UnitOfLength.INCHES,
        SensorStateClass.MEASUREMENT,
    ),
    "firmware": ("mdi:chip", None, None),
    "printhead_temperature": (
        "mdi:thermometer",
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
    ),
    # Zebra reports this lifetime value as printed dots, not a physical distance.
    "printhead_usage": ("mdi:counter", "dots", SensorStateClass.TOTAL_INCREASING),
    "ribbon_inserted": ("mdi:ribbon", None, None),
    "ribbon_remaining": (
        "mdi:ribbon",
        UnitOfLength.METERS,
        SensorStateClass.MEASUREMENT,
    ),
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
        self.entry = entry
        self.key = key
        icon, unit, state_class = SENSORS[key]
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        if key == "printhead_temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
        if key in ("firmware", "printhead_usage"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the latest polled value."""
        if self.key == "estimated_media_remaining":
            return self._estimated_media_remaining()
        value = self.coordinator.data.get(self.key)
        if self.key == "ribbon_inserted":
            return None if value is None else "Loaded" if value else "Not loaded"
        return value

    @property
    def available(self):
        """Mark sensors unavailable when their reading is missing."""
        if self.key == "estimated_media_remaining":
            return (
                super().available
                and self._estimated_media_remaining() is not None
            )
        return super().available and self.coordinator.data.get(self.key) is not None

    def _estimated_media_remaining(self) -> float | None:
        """Estimate media from the printer's cumulative feed counter."""
        if self.key != "estimated_media_remaining":
            return None

        options = self.entry.options
        current_raw = self.coordinator.data.get("total_print_length")
        roll_length_raw = options.get(CONF_MEDIA_ROLL_LENGTH_INCHES)
        baseline_raw = options.get(CONF_MEDIA_ROLL_BASELINE_INCHES)
        remaining_raw = options.get(CONF_MEDIA_ROLL_REMAINING_INCHES)
        if isinstance(current_raw, bool) or isinstance(baseline_raw, bool):
            return None
        try:
            current = int(current_raw)
            baseline = int(baseline_raw)
            roll_length = float(roll_length_raw)
            remaining_at_baseline = float(remaining_raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if (
            current < 0
            or baseline < 0
            or not math.isfinite(roll_length)
            or not math.isfinite(remaining_at_baseline)
            or roll_length <= 0
            or remaining_at_baseline < 0
            or remaining_at_baseline > roll_length
        ):
            return None
        if current < baseline:
            # The cumulative counter was reset or rolled back. The user must
            # establish a fresh baseline to avoid displaying a false estimate.
            return None

        media_fed_since_baseline = current - baseline
        if media_fed_since_baseline >= remaining_at_baseline:
            return 0.0
        return remaining_at_baseline - media_fed_since_baseline

    @property
    def extra_state_attributes(self):
        """Expose simultaneous printer conditions on the status sensor."""
        if self.key == "estimated_media_remaining":
            return {
                "roll_length_inches": self.entry.options.get(
                    CONF_MEDIA_ROLL_LENGTH_INCHES
                ),
                "remaining_at_baseline_inches": self.entry.options.get(
                    CONF_MEDIA_ROLL_REMAINING_INCHES
                ),
            }
        if self.key != "operating_status":
            return None
        return {
            "paused": self.coordinator.data.get("status_paused"),
            "errors": self.coordinator.data.get("status_errors"),
            "warnings": self.coordinator.data.get("status_warnings"),
            "communication_error": self.coordinator.last_communication_error,
            "optional_read_errors": self.coordinator.data.get(
                "optional_read_errors", []
            ),
        }
