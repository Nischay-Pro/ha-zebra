"""Stable Zebra printer identity and config-entry migration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_PRINTER_ID_PREFIX = "zebra-unique:"


def config_entry_unique_id(printer_unique_id: str) -> str:
    """Return a namespaced config-entry ID from Zebra's stable identifier."""
    return f"{_PRINTER_ID_PREFIX}{printer_unique_id}"


def is_stable_unique_id(unique_id: str | None) -> bool:
    """Return whether an entry ID uses the Zebra-reported identity format."""
    return isinstance(unique_id, str) and unique_id.startswith(_PRINTER_ID_PREFIX)


def async_migrate_config_entry_identity(
    hass: HomeAssistant, entry: ConfigEntry, new_unique_id: str
) -> bool:
    """Move an entry and its existing device to the printer-reported identity."""
    old_unique_id = entry.unique_id
    if old_unique_id == new_unique_id:
        return True

    if any(
        other.entry_id != entry.entry_id and other.unique_id == new_unique_id
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        _LOGGER.warning(
            "Cannot migrate Zebra identity for config entry %s because it is already configured",
            entry.entry_id,
        )
        return False

    registry = dr.async_get(hass)
    old_identifier = (DOMAIN, old_unique_id)
    new_identifier = (DOMAIN, new_unique_id)
    old_device = registry.async_get_device_by_identifier(
        old_identifier, entry.entry_id
    )
    new_device = registry.async_get_device_by_identifier(
        new_identifier, entry.entry_id
    )

    if old_device is not None and new_device is not None and old_device.id != new_device.id:
        _LOGGER.warning(
            "Cannot migrate Zebra identity for config entry %s because its device identifier is already in use",
            entry.entry_id,
        )
        return False

    if old_device is not None and new_device is None:
        identifiers = (old_device.identifiers - {old_identifier}) | {new_identifier}
        try:
            registry.async_update_device(old_device.id, new_identifiers=identifiers)
        except (HomeAssistantError, ValueError):
            _LOGGER.warning(
                "Cannot migrate the device registry identity for Zebra config entry %s",
                entry.entry_id,
                exc_info=True,
            )
            return False

    # If new_device already exists and the old identifier does not, this completes
    # a migration interrupted after updating the device registry but before the
    # config entry was saved.
    hass.config_entries.async_update_entry(entry, unique_id=new_unique_id)
    return True
