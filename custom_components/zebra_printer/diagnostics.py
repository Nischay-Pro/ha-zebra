"""Diagnostics support for the Zebra Printer integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# The config entry currently uses the printer host as its unique ID. Redact
# both values, along with any network identifiers that may be added later.
TO_REDACT = {
    "address",
    "configuration_url",
    "device_id",
    "host",
    "hostname",
    "ip",
    "ip_address",
    "mac",
    "mac_address",
    "network",
    "port",
    "serial",
    "serial_number",
    "token",
    "unique_id",
    "url",
    "webhook_id",
    "alerts_webhook_id",
    "alerts_base_url",
    "callback_base_url",
    "callback_url",
    "password",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return sanitized config-entry, printer, and polling diagnostics."""
    config_entry = async_redact_data(entry.as_dict(), TO_REDACT)
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return {
            "config_entry": config_entry,
            "coordinator": {"loaded": False},
        }

    data = coordinator.data
    diagnostic_data = dict(data) if isinstance(data, dict) else data
    if isinstance(diagnostic_data, dict):
        optional_errors = diagnostic_data.get("optional_read_errors", [])
        diagnostic_data["optional_read_errors"] = [
            str(error).split(":", 1)[0]
            for error in optional_errors
            if isinstance(error, str)
        ]
    reported_fields = sorted(
        key for key, value in data.items() if value is not None
    ) if isinstance(data, dict) else []
    unavailable_fields = sorted(
        key for key, value in data.items() if value is None
    ) if isinstance(data, dict) else []

    last_exception = getattr(coordinator, "last_exception", None)
    last_success = getattr(coordinator, "last_update_success_time", None)
    update_interval = getattr(coordinator, "update_interval", None)

    return {
        "config_entry": config_entry,
        "coordinator": {
            "loaded": True,
            "last_update_success": getattr(coordinator, "last_update_success", None),
            # Keep exception details useful without exposing a host embedded in
            # a connection error message.
            "last_exception_type": (
                type(last_exception).__name__ if last_exception is not None else None
            ),
            "last_successful_update": (
                last_success.isoformat() if isinstance(last_success, datetime) else None
            ),
            "update_interval_seconds": (
                update_interval.total_seconds()
                if isinstance(update_interval, timedelta)
                else None
            ),
        },
        "printer": {
            "data": (
                async_redact_data(diagnostic_data, TO_REDACT)
                if diagnostic_data is not None
                else None
            ),
            # These field names help distinguish unsupported/unavailable optional
            # readings from values the printer currently reports.
            "reported_fields": reported_fields,
            "unavailable_fields": unavailable_fields,
        },
    }
