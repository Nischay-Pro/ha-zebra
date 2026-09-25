"""Resettable Zebra label counter control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ZebraConnectionError
from .const import DOMAIN
from .entity import ZebraEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create reset buttons for counters reported by the printer."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ZebraCounterReset(coordinator, entry, f"reset_counter_{counter}", counter)
        for counter in (1, 2)
        if coordinator.data.get(f"resettable_labels_{counter}") is not None
    )


class ZebraCounterReset(ZebraEntity, ButtonEntity):
    """Reset one of the printer's resettable label odometers."""

    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry, key: str, counter: int) -> None:
        """Initialize a reset button for one counter."""
        super().__init__(coordinator, entry, key)
        self.counter = counter
        self._attr_translation_key = key

    async def async_press(self) -> None:
        """Reset this counter; the lifetime counter cannot be reset."""
        try:
            await self.coordinator.client.set(f"odometer.user_label_count{self.counter}", "0")
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="counter_reset_failed",
            ) from err
        await self.coordinator.async_request_refresh()
