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
    entities = [
        ZebraCounterReset(coordinator, entry, f"reset_counter_{counter}", counter)
        for counter in (1, 2)
    ]
    entities.extend(
        (
            ZebraMediaCalibration(coordinator, entry),
            ZebraTestPrint(coordinator, entry),
        )
    )
    async_add_entities(entities)


class ZebraCounterReset(ZebraEntity, ButtonEntity):
    """Reset one of the printer's resettable label odometers."""

    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry: ConfigEntry, key: str, counter: int) -> None:
        """Initialize a reset button for one counter."""
        super().__init__(coordinator, entry, key)
        self.counter = counter
        self._attr_translation_key = key

    @property
    def available(self) -> bool:
        """Make the button available when the printer reports this counter."""
        return (
            super().available
            and self.coordinator.data.get(f"resettable_labels_{self.counter}")
            is not None
        )

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


class ZebraMediaCalibration(ZebraEntity, ButtonEntity):
    """Run media calibration and refresh printer status."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:printer-pos-cog"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "calibrate_media")
        self._attr_translation_key = "calibrate_media"

    async def async_press(self) -> None:
        """Calibrate the currently loaded labels or other media."""
        try:
            await self.coordinator.client.calibrate_media()
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="media_calibration_failed",
            ) from err
        await self.coordinator.async_request_refresh()


class ZebraTestPrint(ZebraEntity, ButtonEntity):
    """Print one small diagnostic label on the currently loaded media."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:printer-check"
    _TEST_LABEL_ZPL = (
        "^XA"
        "^FO16,16^A0N,20,12^FDZEBRA PRINTER^FS"
        "^FO16,42^A0N,20,12^FDTEST LABEL^FS"
        "^FO16,68^A0N,16,10^FDHOME ASSISTANT^FS"
        "^PQ1,0,1,N"
        "^XZ"
    )

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "test_print")
        self._attr_translation_key = "test_print"

    async def async_press(self) -> None:
        """Send exactly one marked label without retrying it."""
        try:
            await self.coordinator.client.send_print_job(self._TEST_LABEL_ZPL)
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="test_print_failed",
            ) from err
        await self.coordinator.async_request_refresh()
