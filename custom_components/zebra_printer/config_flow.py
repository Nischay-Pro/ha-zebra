"""UI setup for Zebra network printers."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .api import ZebraClient, ZebraConnectionError
from .alerts import (
    ALERT_CONDITIONS,
    CONF_ALERTS_BASE_URL,
    CONF_ALERTS_CONDITIONS,
    CONF_ALERTS_ENABLED,
    CONF_ALERTS_WEBHOOK_ID,
    ZebraAlertConfigurationError,
    ZebraAlertUnsupportedError,
    async_validate_alert_support,
    build_callback_url,
    is_alerts_enabled,
)
from .const import DEFAULT_PORT, DOMAIN
from .discovery import ZebraDiscoveryError, async_discover_printers
from .identity import (
    async_migrate_config_entry_identity,
    config_entry_unique_id,
    is_stable_unique_id,
)

_MANUAL_ENTRY = "__manual__"
_RESCAN_ENTRY = "__rescan__"
_CONF_RESCAN = "rescan"
_ALERT_OPTION_KEYS = {
    CONF_ALERTS_ENABLED,
    CONF_ALERTS_BASE_URL,
    CONF_ALERTS_CONDITIONS,
    CONF_ALERTS_WEBHOOK_ID,
}


class ZebraPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Connect to a Zebra printer through its raw TCP port."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the printer options flow."""
        return ZebraPrinterOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Discover Zebra printers, with a manual setup fallback."""
        if user_input is None and not getattr(self, "_discovery_attempted", False):
            self._discovery_attempted = True
            return await self._async_discover()

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self._manual_schema(),
            )

        if user_input.get(_CONF_RESCAN):
            self._discovery_attempted = True
            return await self._async_discover()

        host = str(user_input.get(CONF_HOST, "")).strip()
        if not host:
            return self.async_show_form(
                step_id="user",
                data_schema=self._manual_schema(),
                errors={"base": "host_required"},
            )

        return await self._async_create_entry(
            host,
            user_input.get(CONF_PORT, DEFAULT_PORT),
            step_id="user",
        )

    async def _async_discover(self):
        """Scan enabled Home Assistant networks and show actionable results."""
        try:
            discovered_hosts = await async_discover_printers(self.hass)
        except ZebraDiscoveryError as err:
            return self.async_show_form(
                step_id="user",
                data_schema=self._manual_schema(),
                errors={"base": err.translation_key},
            )

        configured_hosts = {
            str(entry.data.get(CONF_HOST, "")).casefold()
            for entry in self._async_current_entries()
        }
        new_discovered_hosts = [
            host
            for host in discovered_hosts
            if host.casefold() not in configured_hosts
        ]
        models = await asyncio.gather(
            *(self._async_discovered_model(host) for host in new_discovered_hosts)
        )
        self._discovered_hosts = {
            host: model
            for host, model in zip(new_discovered_hosts, models)
            if model is not None
        }
        if self._discovered_hosts:
            return await self.async_step_discovered()

        if not discovered_hosts:
            discovery_error = "no_printers_found"
        elif not new_discovered_hosts:
            discovery_error = "all_printers_configured"
        else:
            discovery_error = "no_compatible_printers_found"
        return self.async_show_form(
            step_id="user",
            data_schema=self._manual_schema(),
            errors={"base": discovery_error},
        )

    async def async_step_discovered(self, user_input=None):
        """Add a selected discovered printer or use manual setup."""
        if not getattr(self, "_discovered_hosts", None):
            return await self.async_step_user()

        if user_input is not None:
            host = user_input[CONF_HOST]
            if host == _MANUAL_ENTRY:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._manual_schema(),
                )
            if host == _RESCAN_ENTRY:
                return await self._async_discover()
            return await self._async_create_entry(
                host,
                DEFAULT_PORT,
                step_id="discovered",
            )

        return self.async_show_form(
            step_id="discovered",
            data_schema=self._discovered_schema(),
        )

    @staticmethod
    def _manual_schema() -> vol.Schema:
        """Return the manual host and port form."""
        return vol.Schema(
            {
                vol.Optional(CONF_HOST, default=""): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    int, vol.Range(min=1, max=65535)
                ),
                vol.Optional(_CONF_RESCAN, default=False): bool,
            }
        )

    def _discovered_schema(self) -> vol.Schema:
        """Return the discovered printer selector."""
        options = {
            host: f"{model} ({host})"
            for host, model in sorted(self._discovered_hosts.items())
        }
        options[_MANUAL_ENTRY] = "Enter host manually"
        options[_RESCAN_ENTRY] = "Search again"
        return vol.Schema({vol.Required(CONF_HOST): vol.In(options)})

    async def _async_discovered_model(self, host: str) -> str | None:
        """Return the model when a discovered host passes the SGD checks."""
        try:
            return await self._async_get_printer_model(host, DEFAULT_PORT)
        except ZebraConnectionError:
            return None

    async def _async_get_printer_model(self, host: str, port: int) -> str:
        """Verify a Zebra printer and return its reported model."""
        model, _ = await self._async_get_printer_info(host, port)
        return model

    async def _async_get_printer_info(
        self, host: str, port: int
    ) -> tuple[str, str | None]:
        """Verify required readings and optionally return Zebra's stable ID."""
        client = ZebraClient(host, port)
        total_labels = await client.get("odometer.total_label_count")
        if total_labels is None:
            raise ZebraConnectionError("No Zebra label counter found")
        try:
            if int(total_labels) < 0:
                raise ValueError
        except (TypeError, ValueError) as err:
            raise ZebraConnectionError(
                "Zebra returned an invalid lifetime label counter"
            ) from err
        if await client.get("ezpl.print_method") is None:
            raise ZebraConnectionError("No Zebra print method found")
        model = await client.get("device.product_name") or "Zebra Printer"
        try:
            printer_unique_id = await client.get("device.unique_id")
        except ZebraConnectionError:
            printer_unique_id = None
        return model, printer_unique_id.strip() if printer_unique_id else None

    async def _async_create_entry(self, host: str, port: int, *, step_id: str):
        """Validate a printer and create its config entry."""
        errors = {}
        try:
            model, printer_unique_id = await self._async_get_printer_info(host, port)
        except ZebraConnectionError:
            errors["base"] = "cannot_connect"
            schema = (
                self._discovered_schema()
                if step_id == "discovered"
                else self._manual_schema()
            )
            return self.async_show_form(
                step_id=step_id,
                data_schema=schema,
                errors=errors,
            )

        unique_id = (
            config_entry_unique_id(printer_unique_id)
            if printer_unique_id
            else host
        )
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Zebra {model}" if model != "Zebra Printer" else model,
            data={CONF_HOST: host, CONF_PORT: port},
        )

    async def async_step_reconfigure(self, user_input=None):
        """Change the printer's address after verifying a Zebra response."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input.get(CONF_HOST, "")).strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            if not host:
                errors["base"] = "host_required"
            else:
                try:
                    _, printer_unique_id = await self._async_get_printer_info(
                        host, port
                    )
                except ZebraConnectionError:
                    errors["base"] = "cannot_connect"
                else:
                    if is_stable_unique_id(entry.unique_id):
                        if not printer_unique_id:
                            errors["base"] = "identity_unavailable"
                        elif config_entry_unique_id(printer_unique_id) != entry.unique_id:
                            errors["base"] = "identity_mismatch"

                    if not errors:
                        new_unique_id = (
                            config_entry_unique_id(printer_unique_id)
                            if printer_unique_id
                            else host
                        )
                        already_configured = any(
                            other.entry_id != entry.entry_id
                            and other.unique_id == new_unique_id
                            for other in self.hass.config_entries.async_entries(DOMAIN)
                        )
                        if already_configured:
                            errors["base"] = "already_configured"
                        elif not async_migrate_config_entry_identity(
                            self.hass, entry, new_unique_id
                        ):
                            errors["base"] = "identity_conflict"
                        else:
                            await self.async_set_unique_id(new_unique_id)
                            self._abort_if_unique_id_mismatch()
                            return self.async_update_reload_and_abort(
                                entry,
                                data_updates={CONF_HOST: host, CONF_PORT: port},
                            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST, "")
                    ): str,
                    vol.Optional(
                        CONF_PORT,
                        default=entry.data.get(CONF_PORT, DEFAULT_PORT),
                    ): vol.All(int, vol.Range(min=1, max=65535)),
                }
            ),
            errors=errors,
        )


class ZebraPrinterOptionsFlow(config_entries.OptionsFlow):
    """Configure optional printer-originated HTTP alert delivery."""

    async def async_step_init(self, user_input=None):
        """Enable or disable selected Zebra alert conditions."""
        errors: dict[str, str] = {}
        current_options = self.config_entry.options
        if user_input is not None:
            if not user_input[CONF_ALERTS_ENABLED]:
                options = dict(current_options)
                for key in _ALERT_OPTION_KEYS:
                    options.pop(key, None)
                options[CONF_ALERTS_ENABLED] = False
                return self.async_create_entry(
                    title="", data=options
                )

            base_url = str(user_input.get(CONF_ALERTS_BASE_URL, "")).strip()
            conditions = tuple(user_input.get(CONF_ALERTS_CONDITIONS, ()))
            webhook_id = current_options.get(CONF_ALERTS_WEBHOOK_ID)
            if not isinstance(webhook_id, str):
                webhook_id = webhook.async_generate_id()

            if not conditions:
                errors["base"] = "alerts_select_condition"
            else:
                try:
                    build_callback_url(base_url, webhook_id)
                except ZebraAlertConfigurationError:
                    errors["base"] = "alerts_invalid_url"

            if not errors:
                client = ZebraClient(
                    self.config_entry.data[CONF_HOST],
                    self.config_entry.data[CONF_PORT],
                )
                try:
                    await async_validate_alert_support(client, conditions)
                except ZebraAlertUnsupportedError:
                    errors["base"] = "alerts_unsupported"
                except ZebraConnectionError:
                    errors["base"] = "alerts_cannot_connect"

            if not errors:
                options = dict(current_options)
                options.update(
                    {
                        CONF_ALERTS_ENABLED: True,
                        CONF_ALERTS_BASE_URL: base_url,
                        CONF_ALERTS_CONDITIONS: list(conditions),
                        CONF_ALERTS_WEBHOOK_ID: webhook_id,
                    }
                )
                return self.async_create_entry(
                    title="",
                    data=options,
                )

        enabled = is_alerts_enabled(current_options)
        schema = vol.Schema(
            {
                vol.Required(CONF_ALERTS_ENABLED, default=enabled): bool,
                vol.Optional(
                    CONF_ALERTS_BASE_URL,
                    default=current_options.get(CONF_ALERTS_BASE_URL, ""),
                ): str,
                vol.Optional(
                    CONF_ALERTS_CONDITIONS,
                    default=current_options.get(CONF_ALERTS_CONDITIONS, []),
                ): cv.multi_select(ALERT_CONDITIONS),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
