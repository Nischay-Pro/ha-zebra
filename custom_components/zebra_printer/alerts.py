"""Optional printer-originated Zebra alert delivery to Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import ZebraClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_ALERTS_ENABLED = "alerts_enabled"
CONF_ALERTS_BASE_URL = "alerts_base_url"
CONF_ALERTS_CONDITIONS = "alerts_conditions"
CONF_ALERTS_WEBHOOK_ID = "alerts_webhook_id"

EVENT_ZEBRA_PRINTER_ALERT = f"{DOMAIN}_alert"
ALERT_DESTINATION = "HTTP-POST"
ALERT_WEBHOOK_NAME = "Zebra Printer"

# These condition names are defined by Zebra's alerts.conditions command.
# A condition is used only when the printer also reports it as supported.
ALERT_CONDITIONS = (
    "PAPER OUT",
    "RIBBON OUT",
    "HEAD TOO HOT",
    "HEAD COLD",
    "HEAD OPEN",
    "SUPPLY TOO HOT",
    "PRINTER PAUSED",
    "CLEAN PRINTHEAD",
    "MEDIA LOW",
    "RIBBON LOW",
    "REPLACE HEAD",
)


class ZebraAlertConfigurationError(ValueError):
    """An alert callback URL or condition is invalid."""


class ZebraAlertUnsupportedError(ValueError):
    """The printer does not report the selected HTTP alert capability."""


@dataclass(frozen=True)
class ZebraAlertConfiguration:
    """The active webhook and printer alert subscriptions for one entry."""

    webhook_id: str
    callback_url: str
    conditions: tuple[str, ...]


def is_alerts_enabled(options: dict[str, object]) -> bool:
    """Return whether printer-originated events were explicitly enabled."""
    return options.get(CONF_ALERTS_ENABLED) is True


def callback_url_from_options(options: dict[str, object]) -> str | None:
    """Build the full local webhook URL from saved alert options."""
    if not is_alerts_enabled(options):
        return None
    base_url = options.get(CONF_ALERTS_BASE_URL)
    webhook_id = options.get(CONF_ALERTS_WEBHOOK_ID)
    if not isinstance(base_url, str) or not isinstance(webhook_id, str):
        return None
    try:
        return build_callback_url(base_url, webhook_id)
    except ZebraAlertConfigurationError:
        return None


def configuration_from_options(
    options: dict[str, object],
) -> ZebraAlertConfiguration | None:
    """Read enabled alert settings from a config entry's options."""
    callback_url = callback_url_from_options(options)
    webhook_id = options.get(CONF_ALERTS_WEBHOOK_ID)
    raw_conditions = options.get(CONF_ALERTS_CONDITIONS)
    if (
        callback_url is None
        or not isinstance(webhook_id, str)
        or not isinstance(raw_conditions, (list, tuple))
    ):
        return None
    conditions = tuple(
        condition
        for condition in raw_conditions
        if isinstance(condition, str) and condition in ALERT_CONDITIONS
    )
    if not conditions:
        return None
    return ZebraAlertConfiguration(webhook_id, callback_url, conditions)


def build_callback_url(base_url: str, webhook_id: str) -> str:
    """Validate a printer-reachable HTTP base URL and append HA's webhook path."""
    value = base_url.strip()
    if (
        not value
        or not value.isascii()
        or any(character in value for character in ',"<>\\\r\n\t ')
        or len(webhook_id) != 64
        or any(character not in "0123456789abcdef" for character in webhook_id.casefold())
    ):
        raise ZebraAlertConfigurationError
    try:
        parsed = urlsplit(value)
        # Accessing .port validates malformed ports; userinfo would permit a
        # credential to be embedded in the URL sent to the printer.
        _ = parsed.port
    except ValueError as err:
        raise ZebraAlertConfigurationError from err
    if (
        parsed.scheme.casefold() != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ZebraAlertConfigurationError
    path = f"{parsed.path.rstrip('/')}/api/webhook/{webhook_id}"
    callback_url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    # Zebra documents a 255-character maximum for the alert destination field.
    if len(callback_url) > 255:
        raise ZebraAlertConfigurationError
    return callback_url


def _parse_sgd_list(value: str | None) -> set[str]:
    """Parse Zebra's comma-delimited alerts.conditions/destinations result."""
    if not value:
        return set()
    return {
        item.strip().strip('"').upper().replace(" ", "-")
        for item in value.replace("|", ",").split(",")
        if item.strip()
    }


def supported_conditions(value: str | None) -> set[str]:
    """Return supported condition values in the integration's canonical form."""
    return {item.replace("-", " ") for item in _parse_sgd_list(value)}


async def async_validate_alert_support(
    client: ZebraClient, conditions: tuple[str, ...]
) -> None:
    """Raise if the printer does not report the requested HTTP alert support."""
    reported_conditions = await client.get("alerts.conditions")
    reported_destinations = await client.get("alerts.destinations")
    if reported_conditions is None or reported_destinations is None:
        raise ZebraAlertUnsupportedError
    if "HTTP-POST" not in _parse_sgd_list(reported_destinations):
        raise ZebraAlertUnsupportedError
    unavailable = set(conditions) - supported_conditions(reported_conditions)
    if unavailable:
        raise ZebraAlertUnsupportedError


async def _async_send_alert_command(
    client: ZebraClient,
    condition: str,
    callback_url: str,
    *,
    on_set: str,
    on_clear: str,
) -> None:
    """Send one Zebra alerts.add command over the existing SGD connection."""
    argument = f"{condition},{ALERT_DESTINATION},{on_set},{on_clear},{callback_url},0,N,"
    # Zebra documents alerts.add as a Setvar command. It is intentionally sent
    # directly because alerts.add does not behave like a persistent setting
    # that can be verified by reading the same value back with getvar.
    await client.send_sgd_command(f'! U1 setvar "alerts.add" "{argument}"')


async def async_configure_printer_alerts(
    client: ZebraClient, configuration: ZebraAlertConfiguration
) -> None:
    """Replace this entry's matching Zebra rules with its selected conditions."""
    await async_validate_alert_support(client, configuration.conditions)
    for condition in configuration.conditions:
        # Remove an exact prior entry first, then add the requested set/clear
        # events. The webhook URL is unique per enabled config entry.
        await _async_send_alert_command(
            client,
            condition,
            configuration.callback_url,
            on_set="N",
            on_clear="N",
        )
        await _async_send_alert_command(
            client,
            condition,
            configuration.callback_url,
            on_set="Y",
            on_clear="Y",
        )


async def async_remove_printer_alerts(
    client: ZebraClient, configuration: ZebraAlertConfiguration
) -> None:
    """Remove the alert rules that use this entry's exact webhook URL."""
    for condition in configuration.conditions:
        await _async_send_alert_command(
            client,
            condition,
            configuration.callback_url,
            on_set="N",
            on_clear="N",
        )


async def async_register_webhook(
    hass: HomeAssistant,
    entry: ConfigEntry,
    configuration: ZebraAlertConfiguration,
    *,
    expected_printer_unique_id: str | None,
) -> None:
    """Register a local-only Home Assistant webhook for selected alerts."""
    conditions = configuration.conditions

    async def _handle_alert(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Parse Zebra's multipart HTTP POST alert and publish a HA event."""
        try:
            payload = await request.post()
        except (ValueError, web.HTTPRequestEntityTooLarge):
            return web.Response(status=400)

        raw_message = payload.get("alertMsg")
        reported_printer_unique_id = payload.get("uniqueId")
        if (
            webhook_id != configuration.webhook_id
            or not isinstance(raw_message, str)
            or not isinstance(reported_printer_unique_id, str)
            or not reported_printer_unique_id
        ):
            return web.Response(status=400)
        if (
            expected_printer_unique_id is not None
            and reported_printer_unique_id != expected_printer_unique_id
        ):
            return web.Response(status=403)

        # Zebra percent-encodes alertMsg even inside multipart/form-data.
        message = unquote_plus(raw_message).strip()
        normalized_message = message.upper()
        condition = next(
            (candidate for candidate in conditions if candidate in normalized_message),
            None,
        )
        if condition is None:
            # Conditions outside this entry's explicit selection are ignored.
            return web.Response(status=204)

        hass.bus.async_fire(
            EVENT_ZEBRA_PRINTER_ALERT,
            {
                "config_entry_id": entry.entry_id,
                "condition": condition,
                "message": message,
            },
        )
        _LOGGER.debug("Received configured Zebra alert condition %s", condition)
        return web.Response(status=204)

    webhook.async_register(
        hass,
        DOMAIN,
        ALERT_WEBHOOK_NAME,
        configuration.webhook_id,
        _handle_alert,
        allowed_methods=["POST"],
        local_only=True,
    )


def async_unregister_webhook(
    hass: HomeAssistant, configuration: ZebraAlertConfiguration
) -> None:
    """Unregister a previously registered alert webhook."""
    webhook.async_unregister(hass, configuration.webhook_id)
