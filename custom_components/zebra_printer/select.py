"""Print method control for Zebra printers."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ZebraConnectionError
from .const import DOMAIN, METHOD_VALUES, THERMAL_TRANSFER
from .entity import ZebraEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the print-method selector."""
    async_add_entities([ZebraPrintMethod(hass.data[DOMAIN][entry.entry_id], entry, "print_method")])


class ZebraPrintMethod(ZebraEntity, SelectEntity):
    """Read and change Direct Thermal / Thermal Transfer mode."""

    _attr_translation_key = "print_method"
    _attr_icon = "mdi:printer-settings"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(METHOD_VALUES)

    @property
    def current_option(self) -> str | None:
        """Report the printer's actual mode, not the last requested mode."""
        current = self.coordinator.data.get("print_method")
        return next((name for name, value in METHOD_VALUES.items() if value == current), None)

    async def async_select_option(self, option: str) -> None:
        """Apply a mode change and verify it on the printer."""
        if option not in METHOD_VALUES:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_print_method",
            )
        if option == THERMAL_TRANSFER:
            try:
                if await self.coordinator.client.get("ribbon.cartridge.inserted") != "yes":
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="ribbon_required",
                    )
            except ZebraConnectionError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="print_method_change_failed",
                ) from err
        try:
            await self.coordinator.client.set("ezpl.print_method", METHOD_VALUES[option])
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="print_method_change_failed",
            ) from err
        await self.coordinator.async_request_refresh()
