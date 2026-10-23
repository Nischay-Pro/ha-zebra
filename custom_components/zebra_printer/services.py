"""Home Assistant actions for Zebra printers."""

from __future__ import annotations

import math

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
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

SERVICE_PRINT_PDF = "print_pdf"
ATTR_PDF_FILE = "pdf_file"

SERVICE_SEND_FIRMWARE_FILE = "send_firmware_file"
ATTR_FIRMWARE_FILE = "firmware_file"

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

PRINT_PDF_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _one_device_id,
        vol.Required(ATTR_PDF_FILE): cv.string,
    }
)

SET_MEDIA_ROLL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _one_device_id,
        vol.Required(ATTR_ROLL_LENGTH_INCHES): _positive_finite_length,
        vol.Optional(ATTR_REMAINING_LENGTH_INCHES): _nonnegative_finite_length,
    }
)

SEND_FIRMWARE_FILE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _one_device_id,
        vol.Required(ATTR_FIRMWARE_FILE): cv.string,
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


def _read_uploaded_firmware(hass: HomeAssistant, file_id: str) -> bytes:
    """Read and consume a file uploaded through Home Assistant's file selector."""
    with process_uploaded_file(hass, file_id) as firmware_path:
        return firmware_path.read_bytes()


def _read_uploaded_pdf(hass: HomeAssistant, file_id: str) -> bytes:
    """Read and consume a PDF uploaded through Home Assistant's file selector."""
    with process_uploaded_file(hass, file_id) as pdf_path:
        return pdf_path.read_bytes()


class MediaRollBaselineError(ValueError):
    """The printer's media counter cannot establish a safe roll baseline."""


async def async_get_media_roll_baseline(coordinator) -> int | float:
    """Refresh the printer and return a valid lifetime media counter."""
    await coordinator.async_request_refresh()
    if not coordinator.last_update_success:
        raise MediaRollBaselineError(
            "Could not read the printer's lifetime media counter; the roll baseline was not changed"
        )

    current_length = coordinator.data.get("total_print_length")
    if not isinstance(current_length, (int, float)) or isinstance(
        current_length, bool
    ):
        raise MediaRollBaselineError(
            "The printer's lifetime media counter is unavailable; the roll baseline was not changed"
        )
    try:
        finite_length = float(current_length)
    except (TypeError, ValueError, OverflowError) as err:
        raise MediaRollBaselineError(
            "The printer's lifetime media counter is unavailable; the roll baseline was not changed"
        ) from err
    if not math.isfinite(finite_length) or finite_length < 0:
        raise MediaRollBaselineError(
            "The printer's lifetime media counter is unavailable; the roll baseline was not changed"
        )
    return current_length


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
            active_virtual_device = await coordinator.client.get("apl.enable")
        except ZebraConnectionError as err:
            raise HomeAssistantError(
                f"Could not check the printer's active virtual device: {err}"
            ) from err
        if (
            isinstance(active_virtual_device, str)
            and active_virtual_device.strip().casefold() == "pdf"
        ):
            raise ServiceValidationError(
                "PDF Direct is active. Disable it with apl.enable=none and "
                "restart the printer if required before sending ZPL"
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
        try:
            current_length = await async_get_media_roll_baseline(coordinator)
        except MediaRollBaselineError as err:
            raise ServiceValidationError(str(err)) from err

        # Merge with existing options so printer-alert settings remain intact.
        options = dict(entry.options)
        options[CONF_MEDIA_ROLL_LENGTH_INCHES] = roll_length
        options[CONF_MEDIA_ROLL_BASELINE_INCHES] = current_length
        options[CONF_MEDIA_ROLL_REMAINING_INCHES] = remaining
        hass.config_entries.async_update_entry(entry, options=options)

    async def async_print_pdf(call: ServiceCall) -> None:
        """Send one uploaded PDF when PDF Direct is already active."""
        entry = _get_config_entry(hass, call.data[ATTR_DEVICE_ID][0])
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            raise ServiceValidationError(
                "The selected Zebra Printer is not ready to send PDF labels"
            )

        if coordinator.file_transfer_lock.locked():
            raise ServiceValidationError(
                "A file transfer is already in progress for this printer"
            )
        async with coordinator.file_transfer_lock:
            try:
                pdf = await hass.async_add_executor_job(
                    _read_uploaded_pdf,
                    hass,
                    call.data[ATTR_PDF_FILE],
                )
            except (OSError, ValueError) as err:
                raise ServiceValidationError(
                    "The uploaded PDF could not be read or is no longer available"
                ) from err
            if not pdf:
                raise ServiceValidationError("The PDF file is empty")
            if not pdf.startswith(b"%PDF-"):
                raise ServiceValidationError(
                    "The uploaded file does not have a valid PDF signature"
                )

            try:
                active_virtual_device = await coordinator.client.get("apl.enable")
            except ZebraConnectionError as err:
                raise ServiceValidationError(
                    "Could not check whether PDF Direct is enabled on the printer"
                ) from err

            active_virtual_device = (
                active_virtual_device.strip().casefold()
                if isinstance(active_virtual_device, str)
                else None
            )
            if active_virtual_device != "pdf":
                if active_virtual_device in (None, "", "none"):
                    raise ServiceValidationError(
                        "PDF Direct is not active. Enable it on the printer with "
                        'apl.enable="pdf", restart the printer if required, and '
                        "retry. Changing the virtual device can affect ZPL printing"
                    )
                raise ServiceValidationError(
                    f"Printer virtual device '{active_virtual_device}' is active; "
                    "refusing to replace it with PDF Direct"
                )

            try:
                await coordinator.client.send_pdf_file(pdf)
            except ZebraConnectionError as err:
                raise HomeAssistantError(
                    f"Could not send the PDF file: {err}"
                ) from err

    async def async_send_firmware_file(call: ServiceCall) -> None:
        """Send a local Zebra firmware file to a configured printer."""
        entry = _get_config_entry(hass, call.data[ATTR_DEVICE_ID][0])
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            raise ServiceValidationError(
                "The selected Zebra Printer is not ready to send a firmware file"
            )

        if coordinator.file_transfer_lock.locked():
            raise ServiceValidationError(
                "A file transfer is already in progress for this printer"
            )
        async with coordinator.file_transfer_lock:
            try:
                firmware = await hass.async_add_executor_job(
                    _read_uploaded_firmware,
                    hass,
                    call.data[ATTR_FIRMWARE_FILE],
                )
            except (OSError, ValueError) as err:
                raise ServiceValidationError(
                    "The uploaded firmware file could not be read or is no longer available"
                ) from err
            if not firmware:
                raise ServiceValidationError("The firmware file is empty")
            try:
                await coordinator.client.send_firmware_file(firmware)
            except ZebraConnectionError as err:
                raise HomeAssistantError(
                    f"Could not send the firmware file: {err}"
                ) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_PRINT,
        async_print,
        schema=PRINT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PRINT_PDF,
        async_print_pdf,
        schema=PRINT_PDF_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_FIRMWARE_FILE,
        async_send_firmware_file,
        schema=SEND_FIRMWARE_FILE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MEDIA_ROLL,
        async_set_media_roll,
        schema=SET_MEDIA_ROLL_SCHEMA,
    )
