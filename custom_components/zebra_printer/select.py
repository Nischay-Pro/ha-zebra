"""Printer configuration selectors for Zebra printers."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ZebraConnectionError
from .const import (
    DOMAIN,
    METHOD_VALUES,
    RIBBON_CARTRIDGE_FEATURE,
    RIBBON_LOW_WARNING_CHOICES,
    RIBBON_LOW_WARNING_OPTIONS_BY_VALUE,
    RIBBON_WARNING_VARIABLE,
    THERMAL_TRANSFER,
    is_ribbon_cartridge_capable,
)
from .entity import ZebraEntity

MEDIA_TYPE_VARIABLE = "ezpl.media_type"
MEDIA_TYPE_VALUES = {
    "Continuous": "continuous",
    "Gap / Web": "gap/notch",
    "Mark / Notch": "mark",
}
MEDIA_TYPE_OPTIONS_BY_VALUE = {value: option for option, value in MEDIA_TYPE_VALUES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create selectors and let optional availability follow printer readings."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        (
            ZebraPrintMethod(coordinator, entry, "print_method"),
            ZebraRibbonLowWarning(coordinator, entry, "ribbon_low_warning"),
            ZebraMediaType(coordinator, entry, "media_type"),
        )
    )


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


class ZebraRibbonLowWarning(ZebraEntity, SelectEntity):
    """Set the warning point for a supported ribbon cartridge."""

    _attr_translation_key = "ribbon_low_warning"
    _attr_icon = "mdi:ribbon"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(RIBBON_LOW_WARNING_CHOICES)

    @property
    def available(self) -> bool:
        """Only offer the threshold while the cartridge feature is supported."""
        return super().available and is_ribbon_cartridge_capable(
            self.coordinator.data.get("ribbon_cartridge_status")
        )

    @property
    def current_option(self) -> str | None:
        """Return the currently configured warning threshold."""
        value = self.coordinator.data.get("ribbon_low_warning")
        return RIBBON_LOW_WARNING_OPTIONS_BY_VALUE.get(str(value).casefold())

    async def async_select_option(self, option: str) -> None:
        """Set and verify a supported low-ribbon warning threshold."""
        if option not in RIBBON_LOW_WARNING_CHOICES:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_ribbon_warning",
            )
        try:
            status = await self.coordinator.client.get(RIBBON_CARTRIDGE_FEATURE)
            if not is_ribbon_cartridge_capable(status):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="ribbon_cartridge_not_present",
                )
            await self.coordinator.client.set(
                RIBBON_WARNING_VARIABLE, RIBBON_LOW_WARNING_CHOICES[option]
            )
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="ribbon_warning_change_failed",
            ) from err
        await self.coordinator.async_request_refresh()

class ZebraMediaType(ZebraEntity, SelectEntity):
    """Select the loaded media sensing mode."""

    _attr_translation_key = "media_type"
    _attr_icon = "mdi:label-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(MEDIA_TYPE_VALUES)

    @property
    def available(self) -> bool:
        """Only expose the selector while the printer reports a supported value."""
        return super().available and self.coordinator.data.get("media_type") in MEDIA_TYPE_OPTIONS_BY_VALUE

    @property
    def current_option(self) -> str | None:
        """Return the current media mode read from the printer."""
        return MEDIA_TYPE_OPTIONS_BY_VALUE.get(self.coordinator.data.get("media_type"))

    async def async_select_option(self, option: str) -> None:
        """Set and verify a supported media sensing mode."""
        if option not in MEDIA_TYPE_VALUES:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_media_type",
            )
        try:
            await self.coordinator.client.set(MEDIA_TYPE_VARIABLE, MEDIA_TYPE_VALUES[option])
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="print_configuration_change_failed",
            ) from err
        await self.coordinator.async_request_refresh()
