"""Home Assistant actions for Zebra printers."""

from __future__ import annotations

import math

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .api import ZebraConnectionError
from .const import (
    CONF_MEDIA_ROLL_BASELINE_INCHES,
    CONF_MEDIA_ROLL_LENGTH_INCHES,
    CONF_MEDIA_ROLL_REMAINING_INCHES,
    DOMAIN,
)

SERVICE_PRINT = "print"
ATTR_ZPL = "zpl"

SERVICE_SET_MEDIA_ROLL = "set_media_roll"
ATTR_ROLL_LENGTH_INCHES = "roll_length_inches"
ATTR_REMAINING_LENGTH_INCHES = "remaining_length_inches"


def _finite_length(value: object, *, allow_zero: bool) -> float:
    """Validate a finite length in inches without imposing an upper cap."""
    if isinstance(value, bool):
        raise vol.Invalid("Length must be a finite number")
    try:
        length = float(value)
    except (TypeError, ValueError, OverflowError) as err:
        raise vol.Invalid("Length must be a finite number") from err
    if not math.isfinite(length) or length < 0 or (length == 0 and not allow_zero):
        requirement = "nonnegative" if allow_zero else "positive"
        raise vol.Invalid(f"Length must be a {requirement} finite number")
    return length


def _positive_finite_length(value: object) -> float:
    """Validate a positive finite length."""
    return _finite_length(value, allow_zero=False)


def _nonnegative_finite_length(value: object) -> float:
    """Validate a nonnegative finite length."""
    return _finite_length(value, allow_zero=True)


def _one_device_id(value: object) -> list[str]:
    """Require a single device target for this print action."""
    device_ids = [value] if isinstance(value, str) else value
    if (
        not isinstance(device_ids, list)
        or len(device_ids) != 1
        or not isinstance(device_ids[0], str)
        or not device_ids[0]
    ):
        raise vol.Invalid("Select exactly one Zebra Printer device")
    return device_ids


PRINT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _one_device_id,
        vol.Required(ATTR_ZPL): cv.string,
    }
)

SET_MEDIA_ROLL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _one_device_id,
        vol.Required(ATTR_ROLL_LENGTH_INCHES): _positive_finite_length,
        vol.Optional(ATTR_REMAINING_LENGTH_INCHES): _nonnegative_finite_length,
    }
)


def _get_config_entry(hass: HomeAssistant, device_id: str) -> ConfigEntry:
    """Resolve a selected device to its loaded Zebra config entry."""
    lookup = getattr(dr, "async_get_device_and_config_entry_for_domain", None)
    if lookup is None:
        # Keep compatibility with Home Assistant versions before the scoped
        # device/config-entry lookup helper was added.
        device = dr.async_get(hass).async_get(device_id)
        if device is None:
            raise ServiceValidationError("The selected device was not found")
        entries = [
            entry
            for entry_id in device.config_entries
            if (entry := hass.config_entries.async_get_entry(entry_id)) is not None
            and entry.domain == DOMAIN
        ]
        entry = entries[0] if len(entries) == 1 else None
    else:
        device, entry = lookup(hass, device_id, domain=DOMAIN)
        if device is None:
            raise ServiceValidationError("The selected device was not found")

    if entry is None:
        raise ServiceValidationError(
            "The selected device does not identify a Zebra Printer configuration"
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("The selected Zebra Printer is not loaded")
    return entry


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register Zebra service actions."""

    async def async_print(call: ServiceCall) -> None:
        """Send raw ZPL once to the selected configured printer."""
        zpl = call.data[ATTR_ZPL]

        entry = _get_config_entry(hass, call.data[ATTR_DEVICE_ID][0])
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            raise ServiceValidationError(
                "The selected Zebra Printer is not ready to send print jobs"
            )
        try:
            await coordinator.client.send_print_job(zpl)
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                f"Could not send ZPL to the printer: {err}"
            ) from err

    async def async_set_media_roll(call: ServiceCall) -> None:
        """Save roll size and baseline the estimate to the current counter."""
        roll_length = call.data[ATTR_ROLL_LENGTH_INCHES]
        remaining = call.data.get(ATTR_REMAINING_LENGTH_INCHES, roll_length)
        if remaining > roll_length:
            raise ServiceValidationError(
                "Remaining media length cannot exceed the full roll length"
            )

        entry = _get_config_entry(hass, call.data[ATTR_DEVICE_ID][0])
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            raise ServiceValidationError(
                "The selected Zebra Printer is not ready to set a media roll"
            )

        # Establish the baseline from a fresh odometer reading, never stale data.
        await coordinator.async_request_refresh()
        if not coordinator.last_update_success:
            raise ServiceValidationError(
                "Could not read the printer's lifetime media counter; the roll baseline was not changed"
            )
        current_length = coordinator.data.get("total_print_length")
        if (
            not isinstance(current_length, (int, float))
            or isinstance(current_length, bool)
            or not math.isfinite(float(current_length))
            or current_length < 0
        ):
            raise ServiceValidationError(
                "The printer's lifetime media counter is unavailable; the roll baseline was not changed"
            )

        # Merge with existing options so printer-alert settings remain intact.
        options = dict(entry.options)
        options[CONF_MEDIA_ROLL_LENGTH_INCHES] = roll_length
        options[CONF_MEDIA_ROLL_BASELINE_INCHES] = current_length
        options[CONF_MEDIA_ROLL_REMAINING_INCHES] = remaining
        hass.config_entries.async_update_entry(entry, options=options)

    hass.services.async_register(
        DOMAIN,
        SERVICE_PRINT,
        async_print,
        schema=PRINT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MEDIA_ROLL,
        async_set_media_roll,
        schema=SET_MEDIA_ROLL_SCHEMA,
    )