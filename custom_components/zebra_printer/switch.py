"""Printer pause control."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
    """Create a switch that pauses or resumes printing."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ZebraPrintingPausedSwitch(coordinator, entry)])


class ZebraPrintingPausedSwitch(ZebraEntity, SwitchEntity):
    """Reflect and control the printer's paused state."""

    _attr_icon = "mdi:pause"
    _attr_translation_key = "pause_control"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "pause_control")

    @property
    def available(self) -> bool:
        """Require a valid paused-state reading before enabling the control."""
        return super().available and isinstance(
            self.coordinator.data.get("status_paused"), bool
        )

    @property
    def is_on(self) -> bool:
        """Return true while the printer is paused."""
        return self.coordinator.data.get("status_paused") is True

    async def async_turn_on(self, **kwargs) -> None:
        """Pause after the label currently printing is complete."""
        await self._send_pause_command("~PP")

    async def async_turn_off(self, **kwargs) -> None:
        """Resume printing on the printer."""
        await self._send_pause_command("~PS")

    async def _send_pause_command(self, command: str) -> None:
        try:
            await self.coordinator.client.send_printer_control_command(command)
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="pause_control_failed",
            ) from err
        await self.coordinator.async_request_refresh()
