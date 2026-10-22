"""Focused unit coverage for the integration's optional feature modules."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from types import SimpleNamespace

import probatio
from unittest.mock import AsyncMock, Mock, patch

import test_controls as controls
ZebraConnectionError = controls.api_module.ZebraConnectionError


def _module(name, *, package=False):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    if package and not hasattr(module, "__path__"):
        module.__path__ = []
    return module


# Expand the lightweight Home Assistant test doubles installed by test_controls.
ha = _module("homeassistant", package=True)
components = _module("homeassistant.components", package=True)
helpers = _module("homeassistant.helpers", package=True)
ha_typing = _module("homeassistant.helpers.typing")
ha_typing.ConfigType = dict
helpers.typing = ha_typing
config_entries = _module("homeassistant.config_entries")
const = _module("homeassistant.const")
core = _module("homeassistant.core")
exceptions = _module("homeassistant.exceptions")
update_coordinator = _module("homeassistant.helpers.update_coordinator")
entity_platform = _module("homeassistant.helpers.entity_platform")
ha.config_entries = config_entries
ha.components = components
ha.helpers = helpers

config_entries.ConfigEntryState = SimpleNamespace(LOADED="loaded")


class _ConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    async def async_set_unique_id(self, unique_id):
        self._new_unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        return None

    def _abort_if_unique_id_mismatch(self):
        return None

    def _async_current_entries(self):
        return getattr(self, "current_entries", [])

    def _get_reconfigure_entry(self):
        return self.reconfigure_entry

    def async_update_reload_and_abort(self, entry, **kwargs):
        return {"type": "update_reload", "entry": entry, **kwargs}


class _OptionsFlow:
    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_show_menu(self, **kwargs):
        return {"type": "menu", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


config_entries.ConfigFlow = _ConfigFlow
config_entries.OptionsFlow = _OptionsFlow
config_entries.ConfigEntry = type("ConfigEntry", (), {})

const.CONF_HOST = "host"
const.CONF_PORT = "port"
const.ATTR_DEVICE_ID = "device_id"
const.Platform = SimpleNamespace(SENSOR="sensor", SELECT="select", BUTTON="button", NUMBER="number")
const.UnitOfSpeed = SimpleNamespace(INCHES_PER_SECOND="in/s")

core.callback = lambda function: function
core.ServiceCall = type("ServiceCall", (), {})

HomeAssistantError = controls.HomeAssistantError


class _ServiceValidationError(HomeAssistantError):
    pass


exceptions.ServiceValidationError = _ServiceValidationError

webhook = _module("homeassistant.components.webhook")
components.webhook = webhook
webhook.async_generate_id = lambda: "a" * 64
webhook.async_register = Mock()
webhook.async_unregister = Mock()

network = _module("homeassistant.components.network")
components.network = network
network.async_get_adapters = AsyncMock(return_value=[])

diagnostics_component = _module("homeassistant.components.diagnostics")
components.diagnostics = diagnostics_component


def _redact(value, keys):
    if isinstance(value, dict):
        return {
            key: _redact(item, keys)
            for key, item in value.items()
            if key not in keys
        }
    if isinstance(value, list):
        return [_redact(item, keys) for item in value]
    return value


diagnostics_component.async_redact_data = _redact

device_registry = _module("homeassistant.helpers.device_registry")
helpers.device_registry = device_registry
device_registry.async_get = lambda hass: hass.device_registry

config_validation = _module("homeassistant.helpers.config_validation")
helpers.config_validation = config_validation
config_validation.string = str
config_validation.positive_float = probatio.All(
    probatio.Coerce(float), probatio.NonNegative()
)
config_validation.multi_select = lambda options: ("multi_select", tuple(options))

number_component = _module("homeassistant.components.number")
components.number = number_component
number_component.NumberEntity = type("NumberEntity", (), {})
number_component.NumberMode = SimpleNamespace(SLIDER="slider")

update_coordinator.UpdateFailed = type("UpdateFailed", (Exception,), {})


class _DataUpdateCoordinator:
    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = {}
        self.last_update_success = True
        self.last_exception = None

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

    async def async_request_refresh(self):
        self.refresh_count = getattr(self, "refresh_count", 0) + 1
        self.data = await self._async_update_data()


update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator

vol = _module("voluptuous")


class _VolInvalid(Exception):
    pass


class _VolSchema:
    def __init__(self, schema):
        self.schema = schema

    def __call__(self, value):
        return value


vol.Invalid = _VolInvalid
vol.Schema = _VolSchema
vol.Required = lambda key, **kwargs: key
vol.Optional = lambda key, **kwargs: key
vol.All = lambda *validators: validators
vol.Range = lambda **kwargs: ("range", kwargs)
vol.In = lambda values: ("in", values)

aiohttp = _module("aiohttp", package=True)
web = _module("aiohttp.web")
aiohttp.web = web


class _HTTPRequestEntityTooLarge(Exception):
    pass


class _Response:
    def __init__(self, *, status):
        self.status = status


web.Request = type("Request", (), {})
web.HTTPRequestEntityTooLarge = _HTTPRequestEntityTooLarge
web.Response = _Response

integration_dir = (
    Path(controls.__file__).resolve().parents[1]
    / "custom_components"
    / "zebra_printer"
)
alerts_module = importlib.import_module("custom_components.zebra_printer.alerts")
config_flow_module = importlib.import_module("custom_components.zebra_printer.config_flow")
diagnostics_module = importlib.import_module("custom_components.zebra_printer.diagnostics")
discovery_module = importlib.import_module("custom_components.zebra_printer.discovery")
identity_module = importlib.import_module("custom_components.zebra_printer.identity")
number_module = importlib.import_module("custom_components.zebra_printer.number")
services_module = importlib.import_module("custom_components.zebra_printer.services")

integration_spec = importlib.util.spec_from_file_location(
    "custom_components.zebra_printer.integration",
    integration_dir / "__init__.py",
)
assert integration_spec is not None and integration_spec.loader is not None
integration_module = importlib.util.module_from_spec(integration_spec)
sys.modules[integration_spec.name] = integration_module
integration_spec.loader.exec_module(integration_module)


class FeatureCoverageSmokeTest(unittest.TestCase):
    def test_feature_modules_import(self):
        self.assertTrue(alerts_module.ALERT_CONDITIONS)
        self.assertTrue(config_flow_module.ZebraPrinterConfigFlow)
        self.assertTrue(diagnostics_module.TO_REDACT)
        self.assertEqual(discovery_module.DISCOVERY_PORT, 4201)
        self.assertTrue(identity_module.is_stable_unique_id("zebra-unique:id"))
        self.assertTrue(number_module.ZebraPrintTone)
        self.assertTrue(services_module.SERVICE_PRINT)
        self.assertTrue(integration_module.PLATFORMS)
class _SgdClient:
    def __init__(self, values=None, errors=None):
        self.values = values or {}
        self.errors = errors or {}
        self.get_calls = []
        self.set_calls = []
        self.commands = []

    async def get(self, variable):
        self.get_calls.append(variable)
        error = self.errors.get(variable)
        if error is not None:
            raise error
        return self.values.get(variable)

    async def set(self, variable, value):
        self.set_calls.append((variable, value))
        error = self.errors.get(variable)
        if error is not None:
            raise error
        self.values[variable] = value

    async def send_sgd_command(self, command):
        self.commands.append(command)


_WEBHOOK_ID = "a" * 64


def _alert_options(**updates):
    options = {
        alerts_module.CONF_ALERTS_ENABLED: True,
        alerts_module.CONF_ALERTS_BASE_URL: "http://ha.local:8123/base/",
        alerts_module.CONF_ALERTS_WEBHOOK_ID: _WEBHOOK_ID,
        alerts_module.CONF_ALERTS_CONDITIONS: ["PAPER OUT"],
    }
    options.update(updates)
    return options


class AlertConfigurationTest(unittest.TestCase):
    def test_enabled_options_and_callback_url_validation(self):
        self.assertFalse(alerts_module.is_alerts_enabled({}))
        self.assertFalse(alerts_module.is_alerts_enabled({alerts_module.CONF_ALERTS_ENABLED: 1}))
        self.assertTrue(alerts_module.is_alerts_enabled(_alert_options()))
        disabled_options = _alert_options(
            **{alerts_module.CONF_ALERTS_ENABLED: False}
        )
        self.assertFalse(alerts_module.is_alerts_enabled(disabled_options))
        self.assertIsNone(alerts_module.callback_url_from_options(disabled_options))
        self.assertIsNone(alerts_module.callback_url_from_options({}))
        self.assertIsNone(
            alerts_module.callback_url_from_options(
                _alert_options(**{alerts_module.CONF_ALERTS_BASE_URL: None})
            )
        )
        self.assertIsNone(
            alerts_module.callback_url_from_options(
                _alert_options(**{alerts_module.CONF_ALERTS_WEBHOOK_ID: 3})
            )
        )
        self.assertIsNone(
            alerts_module.callback_url_from_options(
                _alert_options(**{alerts_module.CONF_ALERTS_BASE_URL: "ftp://ha.local"})
            )
        )
        self.assertEqual(
            alerts_module.callback_url_from_options(_alert_options()),
            f"http://ha.local:8123/base/api/webhook/{_WEBHOOK_ID}",
        )

    def test_callback_url_rejects_each_invalid_url_class(self):
        invalid_urls = (
            "",
            "http://höst.local",
            "http://ha.local/path with space",
            "http://ha.local:bad",
            "https://ha.local",
            "http:///missing-host",
            "http://user@ha.local",
            "http://user:secret@ha.local",
            "http://ha.local/path?query=1",
            "http://ha.local/path#fragment",
            "http://" + ("a" * 230) + ".local",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(alerts_module.ZebraAlertConfigurationError):
                    alerts_module.build_callback_url(url, _WEBHOOK_ID)
        for webhook_id in ("", "g" * 64):
            with self.subTest(webhook_id=webhook_id):
                with self.assertRaises(alerts_module.ZebraAlertConfigurationError):
                    alerts_module.build_callback_url("http://ha.local", webhook_id)
        with self.assertRaises(alerts_module.ZebraAlertConfigurationError):
            alerts_module.build_callback_url("http://ha.local/path,extra", _WEBHOOK_ID)

    def test_configuration_filters_conditions_and_rejects_incomplete_options(self):
        self.assertIsNone(alerts_module.configuration_from_options({}))
        self.assertIsNone(
            alerts_module.configuration_from_options(
                _alert_options(**{alerts_module.CONF_ALERTS_WEBHOOK_ID: None})
            )
        )
        self.assertIsNone(
            alerts_module.configuration_from_options(
                _alert_options(**{alerts_module.CONF_ALERTS_CONDITIONS: "PAPER OUT"})
            )
        )
        self.assertIsNone(
            alerts_module.configuration_from_options(
                _alert_options(**{alerts_module.CONF_ALERTS_CONDITIONS: ["unknown", 3]})
            )
        )
        configuration = alerts_module.configuration_from_options(
            _alert_options(
                **{
                    alerts_module.CONF_ALERTS_CONDITIONS: [
                        "PAPER OUT",
                        "unknown",
                        3,
                        "HEAD OPEN",
                    ]
                }
            )
        )
        self.assertEqual(configuration.conditions, ("PAPER OUT", "HEAD OPEN"))
        tuple_configuration = alerts_module.configuration_from_options(
            _alert_options(
                **{alerts_module.CONF_ALERTS_CONDITIONS: ("RIBBON OUT",)}
            )
        )
        self.assertEqual(tuple_configuration.conditions, ("RIBBON OUT",))

    def test_sgd_condition_parsing_and_support_validation(self):
        self.assertEqual(alerts_module._parse_sgd_list(None), set())
        self.assertEqual(alerts_module._parse_sgd_list(" , | "), set())
        self.assertEqual(
            alerts_module._parse_sgd_list('"PAPER OUT"|head-open'),
            {"PAPER-OUT", "HEAD-OPEN"},
        )
        self.assertEqual(
            alerts_module.supported_conditions("PAPER-OUT,HEAD OPEN"),
            {"PAPER OUT", "HEAD OPEN"},
        )

    async def _unused(self):
        return None


class AlertCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_validate_alert_support_covers_missing_capability_and_conditions(self):
        for values in (
            {"alerts.conditions": None, "alerts.destinations": "HTTP-POST"},
            {"alerts.conditions": "PAPER OUT", "alerts.destinations": None},
            {"alerts.conditions": "PAPER OUT", "alerts.destinations": "EMAIL"},
            {"alerts.conditions": "PAPER OUT", "alerts.destinations": "HTTP-POST"},
        ):
            with self.subTest(values=values):
                with self.assertRaises(alerts_module.ZebraAlertUnsupportedError):
                    await alerts_module.async_validate_alert_support(
                        _SgdClient(values), ("PAPER OUT", "HEAD OPEN")
                    )
        await alerts_module.async_validate_alert_support(
            _SgdClient(
                {
                    "alerts.conditions": "PAPER-OUT|HEAD OPEN",
                    "alerts.destinations": "EMAIL,HTTP-POST",
                }
            ),
            ("PAPER OUT", "HEAD OPEN"),
        )

    async def test_configure_remove_and_send_alert_commands(self):
        configuration = alerts_module.ZebraAlertConfiguration(
            _WEBHOOK_ID,
            f"http://ha.local/api/webhook/{_WEBHOOK_ID}",
            ("PAPER OUT", "HEAD OPEN"),
        )
        client = _SgdClient(
            {
                "alerts.conditions": "PAPER OUT,HEAD OPEN",
                "alerts.destinations": "HTTP-POST",
            }
        )
        await alerts_module.async_configure_printer_alerts(client, configuration)
        self.assertEqual(len(client.commands), 4)
        self.assertIn('"PAPER OUT,HTTP-POST,N,N,', client.commands[0])
        self.assertIn('"PAPER OUT,HTTP-POST,Y,Y,', client.commands[1])
        await alerts_module.async_remove_printer_alerts(client, configuration)
        self.assertEqual(len(client.commands), 6)
        self.assertIn('"HEAD OPEN,HTTP-POST,N,N,', client.commands[-1])

    async def test_webhook_handler_validates_posts_and_fires_selected_alerts(self):
        configuration = alerts_module.ZebraAlertConfiguration(
            _WEBHOOK_ID,
            f"http://ha.local/api/webhook/{_WEBHOOK_ID}",
            ("PAPER OUT", "HEAD OPEN"),
        )
        registered = {}
        hass = SimpleNamespace(bus=SimpleNamespace(async_fire=Mock()))
        entry = SimpleNamespace(entry_id="entry-1")

        def register(*args, **kwargs):
            registered["handler"] = args[4]
            registered["kwargs"] = kwargs

        with patch.object(webhook, "async_register", side_effect=register):
            await alerts_module.async_register_webhook(
                hass,
                entry,
                configuration,
                expected_printer_unique_id="printer-1",
            )
        self.assertEqual(registered["kwargs"]["allowed_methods"], ["POST"])
        handler = registered["handler"]

        class Request:
            def __init__(self, payload=None, error=None):
                self.payload = payload
                self.error = error

            async def post(self):
                if self.error:
                    raise self.error
                return self.payload

        self.assertEqual(
            (await handler(hass, _WEBHOOK_ID, Request(error=ValueError()))).status,
            400,
        )
        self.assertEqual(
            (
                await handler(
                    hass,
                    _WEBHOOK_ID,
                    Request(error=web.HTTPRequestEntityTooLarge()),
                )
            ).status,
            400,
        )
        invalid_payloads = (
            {"alertMsg": "PAPER OUT"},
            {"alertMsg": 1, "uniqueId": "printer-1"},
            {"alertMsg": "PAPER OUT", "uniqueId": ""},
        )
        for payload in invalid_payloads:
            self.assertEqual(
                (await handler(hass, _WEBHOOK_ID, Request(payload))).status,
                400,
            )
        self.assertEqual(
            (
                await handler(
                    hass,
                    _WEBHOOK_ID,
                    Request({"alertMsg": "PAPER OUT", "uniqueId": "other"}),
                )
            ).status,
            403,
        )
        self.assertEqual(
            (
                await handler(
                    hass,
                    _WEBHOOK_ID,
                    Request({"alertMsg": "MEDIA LOW", "uniqueId": "printer-1"}),
                )
            ).status,
            204,
        )
        self.assertEqual(
            (
                await handler(
                    hass,
                    "wrong-id",
                    Request({"alertMsg": "PAPER OUT", "uniqueId": "printer-1"}),
                )
            ).status,
            400,
        )
        self.assertEqual(hass.bus.async_fire.call_count, 0)
        response = await handler(
            hass,
            _WEBHOOK_ID,
            Request(
                {
                    "alertMsg": "PAPER+OUT%3A+media+empty",
                    "uniqueId": "printer-1",
                }
            ),
        )
        self.assertEqual(response.status, 204)
        hass.bus.async_fire.assert_called_once_with(
            alerts_module.EVENT_ZEBRA_PRINTER_ALERT,
            {
                "config_entry_id": "entry-1",
                "condition": "PAPER OUT",
                "message": "PAPER OUT: media empty",
            },
        )

    async def test_webhook_without_pinned_identity_accepts_printer(self):
        configuration = alerts_module.ZebraAlertConfiguration(
            _WEBHOOK_ID,
            f"http://ha.local/api/webhook/{_WEBHOOK_ID}",
            ("PAPER OUT",),
        )
        registered = {}
        hass = SimpleNamespace(bus=SimpleNamespace(async_fire=Mock()))
        with patch.object(
            webhook,
            "async_register",
            side_effect=lambda *args, **kwargs: registered.update(handler=args[4]),
        ):
            await alerts_module.async_register_webhook(
                hass,
                SimpleNamespace(entry_id="entry-2"),
                configuration,
                expected_printer_unique_id=None,
            )
        request = SimpleNamespace(
            post=AsyncMock(
                return_value={"alertMsg": "PAPER OUT", "uniqueId": "any-printer"}
            )
        )
        response = await registered["handler"](hass, _WEBHOOK_ID, request)
        self.assertEqual(response.status, 204)
        hass.bus.async_fire.assert_called_once()

    def test_unregister_webhook(self):
        configuration = alerts_module.ZebraAlertConfiguration(
            _WEBHOOK_ID, "http://ha.local", ("PAPER OUT",)
        )
        hass = object()
        with patch.object(webhook, "async_unregister") as unregister:
            alerts_module.async_unregister_webhook(hass, configuration)
        unregister.assert_called_once_with(hass, _WEBHOOK_ID)


class IdentityAndDiagnosticsTest(unittest.IsolatedAsyncioTestCase):
    def test_identity_helpers_and_migrations(self):
        self.assertEqual(
            identity_module.config_entry_unique_id("SERIAL"),
            "zebra-unique:SERIAL",
        )
        self.assertTrue(identity_module.is_stable_unique_id("zebra-unique:SERIAL"))
        self.assertFalse(identity_module.is_stable_unique_id("printer.local"))
        self.assertFalse(identity_module.is_stable_unique_id(None))

        entry = SimpleNamespace(entry_id="one", unique_id="old")
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_entries=lambda domain: [entry],
                async_update_entry=Mock(),
            )
        )
        registry = SimpleNamespace(
            async_get_device_by_identifier=Mock(return_value=None),
            async_update_device=Mock(),
        )
        with patch.object(device_registry, "async_get", return_value=registry):
            self.assertTrue(
                identity_module.async_migrate_config_entry_identity(hass, entry, "old")
            )
            duplicate = SimpleNamespace(entry_id="two", unique_id="new")
            hass.config_entries.async_entries = lambda domain: [entry, duplicate]
            self.assertFalse(
                identity_module.async_migrate_config_entry_identity(hass, entry, "new")
            )
            hass.config_entries.async_entries = lambda domain: [entry]
            old_device = SimpleNamespace(id="old-device", identifiers={("zebra_printer", "old")})
            new_device = SimpleNamespace(id="new-device", identifiers={("zebra_printer", "new")})
            registry.async_get_device_by_identifier = Mock(
                side_effect=[old_device, new_device]
            )
            self.assertFalse(
                identity_module.async_migrate_config_entry_identity(hass, entry, "new")
            )
            registry.async_get_device_by_identifier = Mock(
                side_effect=[old_device, None]
            )
            registry.async_update_device.side_effect = ValueError("collision")
            self.assertFalse(
                identity_module.async_migrate_config_entry_identity(hass, entry, "new")
            )
            registry.async_update_device.side_effect = None
            registry.async_get_device_by_identifier.side_effect = [old_device, None]
            self.assertTrue(
                identity_module.async_migrate_config_entry_identity(hass, entry, "new")
            )
            registry.async_update_device.assert_called_with(
                "old-device",
                new_identifiers={("zebra_printer", "new")},
            )
            registry.async_get_device_by_identifier = Mock(
                side_effect=[None, new_device]
            )
            self.assertTrue(
                identity_module.async_migrate_config_entry_identity(hass, entry, "new")
            )
            hass.config_entries.async_update_entry.assert_called()

    async def test_diagnostics_for_unloaded_loaded_and_non_mapping_data(self):
        entry = SimpleNamespace(
            entry_id="entry-1",
            as_dict=lambda: {
                "data": {
                    "host": "secret.local",
                    "port": 9100,
                    "keep": "value",
                    "alerts_webhook_id": "secret-token",
                }
            },
        )
        hass = SimpleNamespace(data={})
        unloaded = await diagnostics_module.async_get_config_entry_diagnostics(hass, entry)
        self.assertEqual(unloaded["coordinator"], {"loaded": False})
        self.assertNotIn("host", unloaded["config_entry"]["data"])

        coordinator = SimpleNamespace(
            data={
                "total_labels": 2,
                "missing": None,
                "host": "secret.local",
                "optional_read_errors": ["sensor.temp: unavailable", 3],
            },
            last_update_success=True,
            last_exception=RuntimeError("connection to secret.local failed"),
            last_update_success_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            update_interval=timedelta(seconds=60),
        )
        hass.data = {"zebra_printer": {"entry-1": coordinator}}
        result = await diagnostics_module.async_get_config_entry_diagnostics(hass, entry)
        self.assertEqual(
            result["printer"]["data"]["optional_read_errors"], ["sensor.temp"]
        )
        self.assertNotIn("host", result["printer"]["data"])
        self.assertEqual(result["printer"]["reported_fields"], ["host", "optional_read_errors", "total_labels"])
        self.assertEqual(result["printer"]["unavailable_fields"], ["missing"])
        self.assertEqual(result["coordinator"]["last_exception_type"], "RuntimeError")
        self.assertEqual(result["coordinator"]["update_interval_seconds"], 60)

        coordinator.data = ["opaque"]
        coordinator.last_exception = None
        coordinator.last_update_success_time = "not-datetime"
        coordinator.update_interval = "not-timedelta"
        result = await diagnostics_module.async_get_config_entry_diagnostics(hass, entry)
        self.assertEqual(result["printer"]["data"], ["opaque"])
        self.assertEqual(result["printer"]["reported_fields"], [])
        self.assertIsNone(result["coordinator"]["last_exception_type"])
        self.assertIsNone(result["coordinator"]["last_successful_update"])
        self.assertIsNone(result["coordinator"]["update_interval_seconds"])

        coordinator.data = None
        result = await diagnostics_module.async_get_config_entry_diagnostics(hass, entry)
        self.assertIsNone(result["printer"]["data"])
class NumericControlTest(unittest.IsolatedAsyncioTestCase):
    async def test_number_setup_and_print_tone_values(self):
        coordinator = controls.FakeCoordinator(
            {"model": "ZD420", "print_tone": 12.3, "print_speed": 4, "print_speed_max": 6}
        )
        hass = SimpleNamespace(data={controls.const_module.DOMAIN: {"test_entry": coordinator}})
        created = []
        await number_module.async_setup_entry(hass, controls._entry(), created.extend)
        self.assertEqual(len(created), 2)
        tone, speed = created

        self.assertTrue(tone.available)
        self.assertEqual(tone.native_value, 12.3)
        coordinator.data["print_tone"] = None
        self.assertIsNone(tone.native_value)
        self.assertFalse(tone.available)
        coordinator.data["print_tone"] = 0
        self.assertTrue(tone.available)

        for invalid in (float("nan"), float("inf"), -0.1, 30.1, 12.35):
            with self.subTest(invalid=invalid):
                with self.assertRaises(HomeAssistantError) as raised:
                    await tone.async_set_native_value(invalid)
                self.assertEqual(
                    raised.exception.translation_key,
                    "unsupported_print_configuration_value",
                )
        client = controls.FakeClient()
        coordinator.client = client
        await tone.async_set_native_value(13.2)
        self.assertEqual(client.set_calls, [("print.tone", "13.2")])
        self.assertEqual(coordinator.refresh_count, 1)

        coordinator.client = controls.FakeClient(fail_write=True)
        with self.assertRaises(HomeAssistantError) as raised:
            await tone.async_set_native_value(13.2)
        self.assertEqual(
            raised.exception.translation_key, "print_configuration_change_failed"
        )
        coordinator.last_update_success = False
        self.assertFalse(tone.available)

    async def test_print_speed_availability_values_and_validation(self):
        coordinator = controls.FakeCoordinator(
            {"model": "ZD420", "print_speed": 4, "print_speed_max": 6}
        )
        speed = number_module.ZebraPrintSpeed(coordinator, controls._entry(), "print_speed")
        self.assertTrue(speed.available)
        self.assertEqual(speed.native_value, 4.0)
        self.assertEqual(speed.native_max_value, 6.0)

        coordinator.data["print_speed"] = None
        self.assertIsNone(speed.native_value)
        self.assertFalse(speed.available)
        coordinator.data["print_speed"] = 4
        coordinator.data["print_speed_max"] = None
        self.assertFalse(speed.available)
        self.assertEqual(speed.native_max_value, 2.0)
        coordinator.data["print_speed_max"] = 6

        for invalid, maximum in (
            (float("nan"), 6),
            (3.5, 6),
            (1, 6),
            (7, 6),
            (3, None),
        ):
            coordinator.data["print_speed_max"] = maximum
            with self.subTest(invalid=invalid, maximum=maximum):
                with self.assertRaises(HomeAssistantError) as raised:
                    await speed.async_set_native_value(float(invalid))
                self.assertEqual(
                    raised.exception.translation_key,
                    "unsupported_print_configuration_value",
                )

        coordinator.data["print_speed_max"] = 6
        client = controls.FakeClient()
        coordinator.client = client
        await speed.async_set_native_value(5.0)
        self.assertEqual(client.set_calls, [("media.speed", "5")])
        self.assertEqual(coordinator.refresh_count, 1)
        coordinator.client = controls.FakeClient(fail_write=True)
        with self.assertRaises(HomeAssistantError) as raised:
            await speed.async_set_native_value(5.0)
        self.assertEqual(
            raised.exception.translation_key, "print_configuration_change_failed"
        )
        coordinator.last_update_success = False
        self.assertFalse(speed.available)


class OptionalSelectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_and_print_method_unknown_ribbon_and_connection_paths(self):
        coordinator = controls.FakeCoordinator(
            {"model": "ZD420", "print_method": "invented"}
        )
        hass = SimpleNamespace(data={controls.const_module.DOMAIN: {"test_entry": coordinator}})
        created = []
        await controls.select_module.async_setup_entry(
            hass, controls._entry(), created.extend
        )
        self.assertEqual(len(created), 3)
        method = created[0]
        self.assertIsNone(method.current_option)

        client = controls.FakeClient({"ribbon.cartridge.inserted": "no"})
        coordinator.client = client
        with self.assertRaises(HomeAssistantError) as raised:
            await method.async_select_option(controls.const_module.THERMAL_TRANSFER)
        self.assertEqual(raised.exception.translation_key, "ribbon_required")
        with self.assertRaises(HomeAssistantError) as raised:
            await method.async_select_option("unknown")
        self.assertEqual(raised.exception.translation_key, "unsupported_print_method")

        client = controls.FakeClient(fail_write=True)
        coordinator.client = client
        with self.assertRaises(HomeAssistantError) as raised:
            await method.async_select_option(controls.const_module.DIRECT_THERMAL)
        self.assertEqual(raised.exception.translation_key, "print_method_change_failed")

        class ReadFailure(controls.FakeClient):
            async def get(self, variable):
                raise controls.api_module.ZebraConnectionError("offline")

        coordinator.client = ReadFailure()
        with self.assertRaises(HomeAssistantError) as raised:
            await method.async_select_option(controls.const_module.THERMAL_TRANSFER)
        self.assertEqual(raised.exception.translation_key, "print_method_change_failed")

    async def test_ribbon_warning_availability_and_write_errors(self):
        coordinator = controls.FakeCoordinator(
            {
                "model": "ZD420",
                "ribbon_cartridge_status": "not present",
                "ribbon_low_warning": "10",
            }
        )
        warning = controls.select_module.ZebraRibbonLowWarning(
            coordinator, controls._entry(), "ribbon_low_warning"
        )
        self.assertTrue(warning.available)
        self.assertEqual(warning.current_option, "10%")
        coordinator.data["ribbon_cartridge_status"] = None
        self.assertFalse(warning.available)
        coordinator.data["ribbon_cartridge_status"] = "present"

        client = controls.FakeClient({"device.feature.ribbon_cartridge": "not available"})
        coordinator.client = client
        with self.assertRaises(HomeAssistantError) as raised:
            await warning.async_select_option("Off")
        self.assertEqual(raised.exception.translation_key, "ribbon_cartridge_not_present")
        with self.assertRaises(HomeAssistantError) as raised:
            await warning.async_select_option("invented")
        self.assertEqual(raised.exception.translation_key, "unsupported_ribbon_warning")

        class ReadFailure(controls.FakeClient):
            async def get(self, variable):
                raise controls.api_module.ZebraConnectionError("offline")

        coordinator.client = ReadFailure()
        with self.assertRaises(HomeAssistantError) as raised:
            await warning.async_select_option("Off")
        self.assertEqual(raised.exception.translation_key, "ribbon_warning_change_failed")

        coordinator.client = controls.FakeClient(
            {"device.feature.ribbon_cartridge": "present"}
        )
        await warning.async_select_option("Off")
        self.assertEqual(
            coordinator.client.set_calls,
            [("ribbon.ribbon_low.warning", "off")],
        )

        coordinator.client = controls.FakeClient(
            {"device.feature.ribbon_cartridge": "present"}, fail_write=True
        )
        with self.assertRaises(HomeAssistantError) as raised:
            await warning.async_select_option("10%")
        self.assertEqual(raised.exception.translation_key, "ribbon_warning_change_failed")

    async def test_media_type_availability_current_option_and_selection(self):
        coordinator = controls.FakeCoordinator(
            {"model": "ZD420", "media_type": "mark"}
        )
        media = controls.select_module.ZebraMediaType(
            coordinator, controls._entry(), "media_type"
        )
        self.assertTrue(media.available)
        self.assertEqual(media.current_option, "Mark / Notch")
        coordinator.data["media_type"] = None
        self.assertFalse(media.available)
        self.assertIsNone(media.current_option)
        with self.assertRaises(HomeAssistantError) as raised:
            await media.async_select_option("unknown")
        self.assertEqual(raised.exception.translation_key, "unsupported_media_type")

        coordinator.client = controls.FakeClient()
        await media.async_select_option("Continuous")
        self.assertEqual(coordinator.client.set_calls, [("ezpl.media_type", "continuous")])
        coordinator.client = controls.FakeClient(fail_write=True)
        with self.assertRaises(HomeAssistantError) as raised:
            await media.async_select_option("Gap / Web")
        self.assertEqual(
            raised.exception.translation_key, "print_configuration_change_failed"
        )


class SensorEstimateTest(unittest.TestCase):
    def _estimated_sensor(self, *, current=500, baseline=400, roll=1000, remaining=600):
        entry = controls._entry()
        entry.options = {
            controls.const_module.CONF_MEDIA_ROLL_LENGTH_INCHES: roll,
            controls.const_module.CONF_MEDIA_ROLL_BASELINE_INCHES: baseline,
            controls.const_module.CONF_MEDIA_ROLL_REMAINING_INCHES: remaining,
        }
        coordinator = controls.FakeCoordinator(
            {"model": "ZD420", "total_print_length": current}
        )
        return controls.sensor_module.ZebraSensor(
            coordinator, entry, "estimated_media_remaining"
        )

    def test_setup_and_native_sensor_values(self):
        coordinator = controls.FakeCoordinator(
            {
                "model": "ZD420",
                "ribbon_inserted": None,
                "operating_status": "Ready",
                "status_paused": False,
                "status_errors": [],
                "status_warnings": [],
            }
        )
        hass = SimpleNamespace(data={controls.const_module.DOMAIN: {"test_entry": coordinator}})
        created = []
        asyncio.run(
            controls.sensor_module.async_setup_entry(hass, controls._entry(), created.extend)
        )
        self.assertEqual(len(created), len(controls.sensor_module.SENSORS))
        sensors = {item.key: item for item in created}
        self.assertIsNone(sensors["ribbon_inserted"].native_value)
        coordinator.data["ribbon_inserted"] = True
        self.assertEqual(sensors["ribbon_inserted"].native_value, "Loaded")
        coordinator.data["ribbon_inserted"] = False
        self.assertEqual(sensors["ribbon_inserted"].native_value, "Not loaded")
        self.assertIsNone(sensors["firmware"].extra_state_attributes)
        self.assertEqual(
            sensors["operating_status"].extra_state_attributes["errors"], []
        )
        self.assertFalse(sensors["total_labels"].available)
        coordinator.data["total_labels"] = 0
        self.assertTrue(sensors["total_labels"].available)

    def test_media_roll_estimate_validates_inputs_and_calculates_remaining(self):
        self.assertEqual(self._estimated_sensor().native_value, 500.0)
        self.assertTrue(self._estimated_sensor().available)
        self.assertEqual(
            self._estimated_sensor(current=1000).native_value,
            0.0,
        )
        invalid_values = (
            {"current": True},
            {"baseline": False},
            {"current": None},
            {"baseline": "bad"},
            {"roll": float("nan")},
            {"roll": float("inf")},
            {"roll": 0},
            {"remaining": float("nan")},
            {"remaining": float("inf")},
            {"remaining": -1},
            {"remaining": 1001},
            {"current": 399},
        )
        for kwargs in invalid_values:
            with self.subTest(kwargs=kwargs):
                sensor = self._estimated_sensor(**kwargs)
                self.assertIsNone(sensor.native_value)
                self.assertFalse(sensor.available)
        wrong_key = controls.sensor_module.ZebraSensor(
            controls.FakeCoordinator({"model": "ZD420"}), controls._entry(), "total_labels"
        )
        self.assertIsNone(wrong_key._estimated_media_remaining())

    def test_sensor_status_and_estimate_attributes(self):
        estimated = self._estimated_sensor()
        self.assertEqual(
            estimated.extra_state_attributes,
            {
                "roll_length_inches": 1000,
                "remaining_at_baseline_inches": 600,
            },
        )
        non_status = controls.sensor_module.ZebraSensor(
            controls.FakeCoordinator({"model": "ZD420"}),
            controls._entry(),
            "firmware",
        )
        self.assertIsNone(non_status.extra_state_attributes)
        status = controls.sensor_module.ZebraSensor(
            controls.FakeCoordinator(
                {
                    "model": "ZD420",
                    "status_paused": True,
                    "status_errors": ["Head open"],
                    "status_warnings": ["Clean printhead"],
                    "optional_read_errors": ["temperature: unavailable"],
                }
            ),
            controls._entry(),
            "operating_status",
        )
        self.assertEqual(
            status.extra_state_attributes,
            {
                "paused": True,
                "errors": ["Head open"],
                "warnings": ["Clean printhead"],
                "communication_error": None,
                "optional_read_errors": ["temperature: unavailable"],
            },
        )
class ServicesCoverageTest(unittest.TestCase):
    def test_length_and_device_id_validators(self):
        self.assertEqual(services_module._positive_finite_length("1.5"), 1.5)
        self.assertEqual(services_module._nonnegative_finite_length(0), 0)
        for value in (True, "bad", object(), float("inf"), float("nan"), -1, 0):
            with self.subTest(value=value), self.assertRaises(vol.Invalid):
                services_module._positive_finite_length(value)
        for value in (False, "bad", object(), float("inf"), float("nan"), -1):
            with self.subTest(value=value), self.assertRaises(vol.Invalid):
                services_module._nonnegative_finite_length(value)
        self.assertEqual(services_module._one_device_id("one"), ["one"])
        self.assertEqual(services_module._one_device_id(["one"]), ["one"])
        for value in ([], ["one", "two"], [""], [1], 3, None):
            with self.subTest(value=value), self.assertRaises(vol.Invalid):
                services_module._one_device_id(value)

    def _entry(self, *, state="loaded", domain=services_module.DOMAIN, options=None):
        return SimpleNamespace(
            entry_id="entry-1", domain=domain, state=state,
            data={"host": "printer.local", "port": 9100},
            options=dict(options or {}),
        )

    def _hass(self, entry):
        device = SimpleNamespace(config_entries={entry.entry_id})
        hass = SimpleNamespace()
        hass.device_registry = SimpleNamespace(async_get=lambda _device_id: device)
        hass.config_entries = SimpleNamespace(
            async_get_entry=lambda _entry_id: entry if _entry_id == entry.entry_id else None,
            async_update_entry=Mock(),
        )
        return hass

    def test_legacy_device_resolution_filters_entries_and_states(self):
        entry = self._entry()
        hass = self._hass(entry)
        self.assertIs(services_module._get_config_entry(hass, "device-1"), entry)

        hass.device_registry.async_get = lambda _device_id: None
        with self.assertRaisesRegex(_ServiceValidationError, "device was not found"):
            services_module._get_config_entry(hass, "device-1")

        hass = self._hass(entry)
        hass.config_entries.async_get_entry = lambda _entry_id: None
        with self.assertRaisesRegex(_ServiceValidationError, "does not identify"):
            services_module._get_config_entry(hass, "device-1")

        other = self._entry(domain="other")
        other.entry_id = "entry-other"
        device = SimpleNamespace(config_entries={entry.entry_id, other.entry_id})
        hass = self._hass(entry)
        hass.device_registry.async_get = lambda _device_id: device
        hass.config_entries.async_get_entry = lambda key: {entry.entry_id: entry, other.entry_id: other}.get(key)
        self.assertIs(services_module._get_config_entry(hass, "device-1"), entry)

        second = self._entry()
        second.entry_id = "entry-2"
        device.config_entries = {entry.entry_id, second.entry_id}
        hass.config_entries.async_get_entry = lambda key: {entry.entry_id: entry, second.entry_id: second}.get(key)
        with self.assertRaisesRegex(_ServiceValidationError, "does not identify"):
            services_module._get_config_entry(hass, "device-1")

        unloaded = self._entry(state="not_loaded")
        hass = self._hass(unloaded)
        with self.assertRaisesRegex(_ServiceValidationError, "not loaded"):
            services_module._get_config_entry(hass, "device-1")

    def test_scoped_device_resolution(self):
        entry = self._entry()
        hass = self._hass(entry)
        lookup = Mock(return_value=(object(), entry))
        services_module.dr.async_get_device_and_config_entry_for_domain = lookup
        try:
            self.assertIs(services_module._get_config_entry(hass, "device-1"), entry)
            lookup.assert_called_once_with(hass, "device-1", domain=services_module.DOMAIN)
            lookup.return_value = (None, None)
            with self.assertRaisesRegex(_ServiceValidationError, "device was not found"):
                services_module._get_config_entry(hass, "device-1")
            lookup.return_value = (object(), None)
            with self.assertRaisesRegex(_ServiceValidationError, "does not identify"):
                services_module._get_config_entry(hass, "device-1")
        finally:
            del services_module.dr.async_get_device_and_config_entry_for_domain

    def test_print_action_registration_and_errors(self):
        entry = self._entry()
        hass = self._hass(entry)
        registered = {}
        hass.data = {services_module.DOMAIN: {}}
        hass.services = SimpleNamespace(
            async_register=lambda domain, name, handler, schema: registered.setdefault(name, handler)
        )
        services_module.async_setup_services(hass)
        self.assertEqual(set(registered), {services_module.SERVICE_PRINT, services_module.SERVICE_SET_MEDIA_ROLL})
        call = SimpleNamespace(data={services_module.ATTR_DEVICE_ID: ["device-1"], services_module.ATTR_ZPL: "^XA^XZ"})
        with self.assertRaisesRegex(_ServiceValidationError, "not ready"):
            asyncio.run(registered[services_module.SERVICE_PRINT](call))

        client = SimpleNamespace(send_print_job=AsyncMock())
        hass.data[services_module.DOMAIN][entry.entry_id] = SimpleNamespace(client=client)
        asyncio.run(registered[services_module.SERVICE_PRINT](call))
        client.send_print_job.assert_awaited_once_with("^XA^XZ")
        client.send_print_job.side_effect = controls.api_module.ZebraConnectionError("offline")
        with self.assertRaises(HomeAssistantError):
            asyncio.run(registered[services_module.SERVICE_PRINT](call))

    def test_set_media_roll_action_validation_and_option_preservation(self):
        entry = self._entry(options={"alerts_enabled": True, "keep": "yes"})
        hass = self._hass(entry)
        registered = {}
        hass.data = {services_module.DOMAIN: {}}
        hass.services = SimpleNamespace(async_register=lambda _d, name, handler, schema: registered.setdefault(name, handler))
        services_module.async_setup_services(hass)
        call = SimpleNamespace(data={services_module.ATTR_DEVICE_ID: ["device-1"], services_module.ATTR_ROLL_LENGTH_INCHES: 100, services_module.ATTR_REMAINING_LENGTH_INCHES: 70})
        handler = registered[services_module.SERVICE_SET_MEDIA_ROLL]
        with self.assertRaisesRegex(_ServiceValidationError, "not ready"):
            asyncio.run(handler(call))
        coordinator = SimpleNamespace(
            data={"total_print_length": 123.5}, last_update_success=True,
            async_request_refresh=AsyncMock(),
        )
        hass.data[services_module.DOMAIN][entry.entry_id] = coordinator
        bad_call = SimpleNamespace(data={**call.data, services_module.ATTR_REMAINING_LENGTH_INCHES: 101})
        with self.assertRaisesRegex(_ServiceValidationError, "cannot exceed"):
            asyncio.run(handler(bad_call))
        asyncio.run(handler(call))
        coordinator.async_request_refresh.assert_awaited_once()
        updated = hass.config_entries.async_update_entry.call_args.kwargs["options"]
        self.assertEqual(updated[services_module.CONF_MEDIA_ROLL_LENGTH_INCHES], 100)
        self.assertEqual(updated[services_module.CONF_MEDIA_ROLL_BASELINE_INCHES], 123.5)
        self.assertEqual(updated[services_module.CONF_MEDIA_ROLL_REMAINING_INCHES], 70)
        self.assertTrue(updated["alerts_enabled"])
        self.assertEqual(updated["keep"], "yes")

        coordinator.last_update_success = False
        with self.assertRaisesRegex(_ServiceValidationError, "baseline was not changed"):
            asyncio.run(handler(call))
        coordinator.last_update_success = True
        for invalid in (None, True, -1, float("inf"), "bad", 10**1000):
            coordinator.data = {"total_print_length": invalid}
            with self.subTest(counter=invalid), self.assertRaisesRegex(_ServiceValidationError, "counter is unavailable"):
                asyncio.run(handler(call))
class ConfigFlowCoverageTest(unittest.TestCase):
    def _flow(self):
        flow = config_flow_module.ZebraPrinterConfigFlow()
        flow.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_entries=lambda _domain: [])
        )
        flow.current_entries = []
        return flow

    def test_user_step_discovery_manual_rescan_and_validation(self):
        flow = self._flow()
        with patch.object(config_flow_module, "async_discover_printers", new=AsyncMock(return_value=["printer.local", "known.local", "old.local"])), patch.object(flow, "_async_discovered_model", new=AsyncMock(side_effect=["ZD420", None])) as model:
            flow.current_entries = [SimpleNamespace(data={"host": "KNOWN.local"})]
            result = asyncio.run(flow.async_step_user())
            self.assertEqual(result["step_id"], "discovered")
            self.assertEqual(flow._discovered_hosts, {"printer.local": "ZD420"})
            self.assertEqual(model.await_count, 2)
        self.assertEqual(asyncio.run(flow.async_step_discovered())["step_id"], "discovered")
        schema = flow._discovered_schema().schema
        selector = schema[config_flow_module.CONF_HOST]
        self.assertIn("printer.local", selector[1])
        self.assertIn(config_flow_module._MANUAL_ENTRY, selector[1])
        self.assertIn(config_flow_module._RESCAN_ENTRY, selector[1])

        flow._discovery_attempted = True
        self.assertEqual(asyncio.run(flow.async_step_user())["step_id"], "user")
        self.assertEqual(asyncio.run(flow.async_step_user({config_flow_module._CONF_RESCAN: True}))["step_id"], "user")
        self.assertEqual(asyncio.run(flow.async_step_user({"host": "  "}))["errors"], {"base": "host_required"})
        with patch.object(flow, "_async_create_entry", new=AsyncMock(return_value={"created": True})) as create:
            self.assertEqual(asyncio.run(flow.async_step_user({"host": " printer.local ", "port": 9200})), {"created": True})
            create.assert_awaited_once_with("printer.local", 9200, step_id="user")

    def test_discovery_errors_empty_configured_and_incompatible(self):
        flow = self._flow()
        with patch.object(config_flow_module, "async_discover_printers", new=AsyncMock(side_effect=(lambda error: (setattr(error, "translation_key", "discovery_network_error") or error))(config_flow_module.ZebraDiscoveryError("network")))):
            self.assertEqual(asyncio.run(flow._async_discover())["errors"], {"base": "discovery_network_error"})
        with patch.object(config_flow_module, "async_discover_printers", new=AsyncMock(return_value=[])):
            self.assertEqual(asyncio.run(flow._async_discover())["errors"], {"base": "no_printers_found"})
        flow.current_entries = [SimpleNamespace(data={"host": "one.local"})]
        with patch.object(config_flow_module, "async_discover_printers", new=AsyncMock(return_value=["one.local"])):
            self.assertEqual(asyncio.run(flow._async_discover())["errors"], {"base": "all_printers_configured"})
        flow.current_entries = []
        with patch.object(config_flow_module, "async_discover_printers", new=AsyncMock(return_value=["one.local"])), patch.object(flow, "_async_discovered_model", new=AsyncMock(return_value=None)):
            self.assertEqual(asyncio.run(flow._async_discover())["errors"], {"base": "no_compatible_printers_found"})
        self.assertEqual(config_flow_module.ZebraPrinterConfigFlow.async_get_options_flow(None).__class__, config_flow_module.ZebraPrinterOptionsFlow)

    def test_discovered_selection_fallback_rescan_and_creation(self):
        flow = self._flow()
        flow._discovery_attempted = True
        self.assertEqual(asyncio.run(flow.async_step_discovered())["step_id"], "user")
        flow._discovered_hosts = {"one.local": "ZD420"}
        self.assertEqual(asyncio.run(flow.async_step_discovered({"host": config_flow_module._MANUAL_ENTRY}))["step_id"], "user")
        with patch.object(flow, "_async_discover", new=AsyncMock(return_value={"scanned": True})) as scan:
            self.assertEqual(asyncio.run(flow.async_step_discovered({"host": config_flow_module._RESCAN_ENTRY}),), {"scanned": True})
            scan.assert_awaited_once()
        with patch.object(flow, "_async_create_entry", new=AsyncMock(return_value={"created": True})) as create:
            self.assertEqual(asyncio.run(flow.async_step_discovered({"host": "one.local"}),), {"created": True})
            create.assert_awaited_once_with("one.local", config_flow_module.DEFAULT_PORT, step_id="discovered")

    def test_printer_verification_and_create_failures(self):
        flow = self._flow()
        client = SimpleNamespace(get=AsyncMock(side_effect=["12", "direct thermal", "ZD420", " serial "]))
        with patch.object(config_flow_module, "ZebraClient", return_value=client):
            self.assertEqual(asyncio.run(flow._async_get_printer_info("host", 9100)), ("ZD420", "serial"))
        client.get = AsyncMock(side_effect=["0", "direct thermal", None, ZebraConnectionError("identity")])
        with patch.object(config_flow_module, "ZebraClient", return_value=client):
            self.assertEqual(asyncio.run(flow._async_get_printer_info("host", 9100)), ("Zebra Printer", None))
        for counter, expected in ((None, "No Zebra label counter"), ("bad", "invalid lifetime"), ("-1", "invalid lifetime")):
            client.get = AsyncMock(return_value=counter)
            with patch.object(config_flow_module, "ZebraClient", return_value=client), self.assertRaisesRegex(ZebraConnectionError, expected):
                asyncio.run(flow._async_get_printer_info("host", 9100))
        client.get = AsyncMock(side_effect=["1", None])
        with patch.object(config_flow_module, "ZebraClient", return_value=client), self.assertRaisesRegex(ZebraConnectionError, "print method"):
            asyncio.run(flow._async_get_printer_info("host", 9100))
        flow._async_get_printer_info = AsyncMock(side_effect=ZebraConnectionError("offline"))
        result = asyncio.run(flow._async_create_entry("host", 9100, step_id="user"))
        self.assertEqual(result["errors"], {"base": "cannot_connect"})
        flow._discovered_hosts = {"host": "ZD420"}
        result = asyncio.run(flow._async_create_entry("host", 9100, step_id="discovered"))
        self.assertEqual(result["step_id"], "discovered")
        flow._async_get_printer_info = AsyncMock(return_value=("ZD420", "serial"))
        result = asyncio.run(flow._async_create_entry("host", 9100, step_id="user"))
        self.assertEqual(result["title"], "Zebra ZD420")
        self.assertEqual(flow._new_unique_id, "zebra-unique:serial")
        flow._async_get_printer_info = AsyncMock(return_value=("Zebra Printer", None))
        result = asyncio.run(flow._async_create_entry("host", 9100, step_id="user"))
        self.assertEqual(result["title"], "Zebra Printer")
        self.assertEqual(flow._new_unique_id, "host")

    def test_reconfigure_all_identity_and_error_paths(self):
        flow = self._flow()
        entry = SimpleNamespace(entry_id="entry-1", unique_id="old-host", data={"host": "old", "port": 9100})
        flow.reconfigure_entry = entry
        self.assertEqual(asyncio.run(flow.async_step_reconfigure())["step_id"], "reconfigure")
        self.assertEqual(asyncio.run(flow.async_step_reconfigure({"host": " "}))["errors"], {"base": "host_required"})
        flow._async_get_printer_info = AsyncMock(side_effect=ZebraConnectionError("offline"))
        self.assertEqual(asyncio.run(flow.async_step_reconfigure({"host": "new"}))["errors"], {"base": "cannot_connect"})

        stable = config_flow_module.config_entry_unique_id("serial")
        entry.unique_id = stable
        flow._async_get_printer_info = AsyncMock(return_value=("ZD420", None))
        self.assertEqual(asyncio.run(flow.async_step_reconfigure({"host": "new"}))["errors"], {"base": "identity_unavailable"})
        flow._async_get_printer_info = AsyncMock(return_value=("ZD420", "different"))
        self.assertEqual(asyncio.run(flow.async_step_reconfigure({"host": "new"}))["errors"], {"base": "identity_mismatch"})
        flow._async_get_printer_info = AsyncMock(return_value=("ZD420", "serial"))
        duplicate = SimpleNamespace(entry_id="other", unique_id=stable)
        flow.hass.config_entries.async_entries = lambda _domain: [entry, duplicate]
        self.assertEqual(asyncio.run(flow.async_step_reconfigure({"host": "new"}))["errors"], {"base": "already_configured"})
        flow.hass.config_entries.async_entries = lambda _domain: [entry]
        with patch.object(config_flow_module, "async_migrate_config_entry_identity", return_value=False):
            self.assertEqual(asyncio.run(flow.async_step_reconfigure({"host": "new"}))["errors"], {"base": "identity_conflict"})
        with patch.object(config_flow_module, "async_migrate_config_entry_identity", return_value=True):
            result = asyncio.run(flow.async_step_reconfigure({"host": "new", "port": 9200}))
        self.assertEqual(result["type"], "update_reload")
        self.assertEqual(result["data_updates"], {"host": "new", "port": 9200})

        entry.unique_id = "old-host"
        flow._async_get_printer_info = AsyncMock(return_value=("ZD420", None))
        with patch.object(config_flow_module, "async_migrate_config_entry_identity", return_value=True):
            result = asyncio.run(flow.async_step_reconfigure({"host": "new"}))
        self.assertEqual(flow._new_unique_id, "new")

    def test_alert_options_are_conditional_and_values_survive_disable(self):
        flow = config_flow_module.ZebraPrinterOptionsFlow()
        base = config_flow_module.CONF_ALERTS_BASE_URL
        conditions = config_flow_module.CONF_ALERTS_CONDITIONS
        enabled = config_flow_module.CONF_ALERTS_ENABLED
        webhook_id = config_flow_module.CONF_ALERTS_WEBHOOK_ID
        saved_options = {
            "keep": "yes",
            enabled: True,
            base: "http://ha.local:8123",
            conditions: ["PAPER OUT"],
            webhook_id: _WEBHOOK_ID,
        }
        flow.config_entry = SimpleNamespace(
            data={"host": "printer.local", "port": 9100},
            options=saved_options,
        )

        initial_form = asyncio.run(flow.async_step_alerts())
        self.assertEqual(initial_form["step_id"], "alerts")
        self.assertEqual(
            set(initial_form["data_schema"].schema),
            {enabled},
        )

        settings_form = asyncio.run(flow.async_step_alerts({enabled: True}))
        self.assertEqual(settings_form["step_id"], "alerts_config")
        self.assertEqual(
            set(settings_form["data_schema"].schema),
            {base, conditions},
        )
        self.assertEqual(
            asyncio.run(flow.async_step_alerts_config())["step_id"],
            "alerts_config",
        )

        disabled = asyncio.run(flow.async_step_alerts({enabled: False}))
        self.assertFalse(disabled["data"][enabled])
        self.assertEqual(disabled["data"]["keep"], "yes")
        self.assertEqual(disabled["data"][base], saved_options[base])
        self.assertEqual(disabled["data"][conditions], saved_options[conditions])
        self.assertEqual(disabled["data"][webhook_id], _WEBHOOK_ID)

        self.assertIn(
            "base",
            asyncio.run(
                flow.async_step_alerts_config(
                    {base: "https://ha.local", conditions: []}
                )
            )["errors"],
        )
        payload = {base: "file:///bad", conditions: ["media_out"]}
        self.assertEqual(
            asyncio.run(flow.async_step_alerts_config(payload))["errors"],
            {"base": "alerts_invalid_url"},
        )
        payload[base] = "http://ha.local"
        with patch.object(
            config_flow_module,
            "async_validate_alert_support",
            new=AsyncMock(
                side_effect=config_flow_module.ZebraAlertUnsupportedError(
                    "unsupported"
                )
            ),
        ):
            self.assertEqual(
                asyncio.run(flow.async_step_alerts_config(payload))["errors"],
                {"base": "alerts_unsupported"},
            )
        with patch.object(
            config_flow_module,
            "async_validate_alert_support",
            new=AsyncMock(side_effect=ZebraConnectionError("offline")),
        ):
            self.assertEqual(
                asyncio.run(flow.async_step_alerts_config(payload))["errors"],
                {"base": "alerts_cannot_connect"},
            )
        with patch.object(
            config_flow_module,
            "async_validate_alert_support",
            new=AsyncMock(),
        ):
            saved = asyncio.run(flow.async_step_alerts_config(payload))
        self.assertTrue(saved["data"][enabled])
        self.assertEqual(saved["data"][webhook_id], _WEBHOOK_ID)
        self.assertTrue(
            all(key in saved["data"] for key in config_flow_module._ALERT_OPTION_KEYS)
        )

        flow.config_entry.options.pop(webhook_id)
        with (
            patch.object(
                config_flow_module.webhook,
                "async_generate_id",
                return_value="b" * 64,
            ),
            patch.object(
                config_flow_module,
                "async_validate_alert_support",
                new=AsyncMock(),
            ),
        ):
            saved = asyncio.run(flow.async_step_alerts_config(payload))
        self.assertEqual(saved["data"][webhook_id], "b" * 64)
        menu = asyncio.run(flow.async_step_init(None))
        self.assertEqual(menu["type"], "menu")
        self.assertEqual(menu["menu_options"], ["media_roll", "alerts"])
        self.assertEqual(
            asyncio.run(flow.async_step_alerts())["step_id"], "alerts"
        )

    def test_media_roll_options_flow_records_full_and_partial_rolls(self):
        flow = config_flow_module.ZebraPrinterOptionsFlow()
        entry = SimpleNamespace(
            entry_id="entry-1",
            data={"host": "printer.local", "port": 9100},
            options={"keep": "yes", "alerts_enabled": True},
        )
        flow.config_entry = entry
        coordinator = SimpleNamespace(
            data={"total_print_length": 1234.5},
            last_update_success=True,
            async_request_refresh=AsyncMock(),
        )
        flow.hass = SimpleNamespace(
            data={config_flow_module.DOMAIN: {entry.entry_id: coordinator}}
        )

        form = asyncio.run(flow.async_step_media_roll())
        self.assertEqual(form["step_id"], "media_roll")
        roll_key = config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES
        remaining_key = config_flow_module.CONF_MEDIA_ROLL_REMAINING_INCHES
        self.assertIn(roll_key, form["data_schema"].schema)
        serialized_fields = probatio.to_field_list(
            probatio.Schema(
                {
                    probatio.Required(roll_key): form["data_schema"].schema[roll_key],
                    probatio.Optional(remaining_key): form["data_schema"].schema[
                        remaining_key
                    ],
                }
            )
        )
        self.assertEqual(
            serialized_fields,
            [
                {
                    "type": "float",
                    "valueMin": 0,
                    "name": roll_key,
                    "required": True,
                },
                {
                    "type": "float",
                    "valueMin": 0,
                    "name": remaining_key,
                    "required": False,
                    "optional": True,
                },
            ],
        )
        self.assertEqual(
            asyncio.run(flow.async_step_media_roll({}))["errors"],
            {"base": "media_roll_length_required"},
        )
        for invalid_roll in (0, -1, float("nan"), float("inf"), True, "bad"):
            with self.subTest(invalid_roll=invalid_roll):
                self.assertEqual(
                    asyncio.run(
                        flow.async_step_media_roll(
                            {roll_key: invalid_roll}
                        )
                    )["errors"],
                    {"base": "media_roll_length_invalid"},
                )
        for invalid_remaining in (-1, float("nan"), float("inf"), True, "bad"):
            with self.subTest(invalid_remaining=invalid_remaining):
                self.assertEqual(
                    asyncio.run(
                        flow.async_step_media_roll(
                            {roll_key: 100, remaining_key: invalid_remaining}
                        )
                    )["errors"],
                    {"base": "media_roll_remaining_invalid"},
                )
        self.assertEqual(
            asyncio.run(
                flow.async_step_media_roll(
                    {
                        config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES: 100,
                        config_flow_module.CONF_MEDIA_ROLL_REMAINING_INCHES: 101,
                    }
                )
            )["errors"],
            {"base": "media_roll_remaining_exceeds_roll"},
        )

        flow.hass.data[config_flow_module.DOMAIN] = {}
        self.assertEqual(
            asyncio.run(
                flow.async_step_media_roll(
                    {config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES: 100}
                )
            )["errors"],
            {"base": "media_roll_printer_not_ready"},
        )
        flow.hass.data[config_flow_module.DOMAIN][entry.entry_id] = coordinator
        coordinator.last_update_success = False
        self.assertEqual(
            asyncio.run(
                flow.async_step_media_roll(
                    {config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES: 100}
                )
            )["errors"],
            {"base": "media_roll_counter_unavailable"},
        )
        coordinator.last_update_success = True
        full_roll = asyncio.run(
            flow.async_step_media_roll(
                {config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES: 1000}
            )
        )
        self.assertEqual(full_roll["type"], "create_entry")
        self.assertEqual(full_roll["data"]["keep"], "yes")
        self.assertTrue(full_roll["data"]["alerts_enabled"])
        self.assertEqual(
            full_roll["data"][config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES],
            1000,
        )
        self.assertEqual(
            full_roll["data"][config_flow_module.CONF_MEDIA_ROLL_BASELINE_INCHES],
            1234.5,
        )
        self.assertEqual(
            full_roll["data"][config_flow_module.CONF_MEDIA_ROLL_REMAINING_INCHES],
            1000,
        )

        entry.options = full_roll["data"]
        coordinator.data["total_print_length"] = 1240
        partial_roll = asyncio.run(
            flow.async_step_media_roll(
                {
                    config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES: 1000,
                    config_flow_module.CONF_MEDIA_ROLL_REMAINING_INCHES: 450,
                }
            )
        )
        self.assertEqual(
            partial_roll["data"][config_flow_module.CONF_MEDIA_ROLL_BASELINE_INCHES],
            1240,
        )
        self.assertEqual(
            partial_roll["data"][config_flow_module.CONF_MEDIA_ROLL_REMAINING_INCHES],
            450,
        )
        entry.options = partial_roll["data"]
        saved_form = asyncio.run(flow.async_step_media_roll())
        self.assertIn(
            config_flow_module.CONF_MEDIA_ROLL_LENGTH_INCHES,
            saved_form["data_schema"].schema,
        )
class _FakeDiscoveryTransport:
    def __init__(self, *, send_error=None):
        self.send_error = send_error
        self.sent = []
        self.closed = False

    def sendto(self, payload, target):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((payload, target))

    def close(self):
        self.closed = True


class _FakeDiscoveryLoop:
    def __init__(self, *, bind_errors=None, send_error=None, replies=(), protocol_error=None):
        self.bind_errors = bind_errors or {}
        self.send_error = send_error
        self.replies = replies
        self.protocol_error = protocol_error
        self.transports = []
        self.protocols = []
        self.bind_calls = []

    async def create_datagram_endpoint(self, protocol_factory, *, local_addr, allow_broadcast):
        self.bind_calls.append((local_addr, allow_broadcast))
        error = self.bind_errors.get(local_addr[0])
        if error:
            raise error
        protocol = protocol_factory()
        transport = _FakeDiscoveryTransport(send_error=self.send_error)
        for host in self.replies:
            protocol.datagram_received(discovery_module._DISCOVERY_RESPONSE_PREFIX + b"reply", (host, 4201))
        if self.protocol_error:
            protocol.error_received(self.protocol_error)
        self.transports.append(transport)
        self.protocols.append(protocol)
        return transport, protocol


class DiscoveryCoverageTest(unittest.TestCase):
    def _run_discovery(self, adapters, loop, *, adapter_error=None):
        async_io = SimpleNamespace(
            get_running_loop=lambda: loop,
            sleep=AsyncMock(),
        )
        adapter_mock = AsyncMock(side_effect=adapter_error) if adapter_error else AsyncMock(return_value=adapters)
        with patch.object(discovery_module, "asyncio", async_io), patch.object(discovery_module.network, "async_get_adapters", new=adapter_mock):
            return asyncio.run(discovery_module.async_discover_printers(SimpleNamespace()))

    def test_protocol_filters_and_records_discovery_responses(self):
        protocol = discovery_module._ZebraDiscoveryProtocol()
        protocol.datagram_received(b"invalid", ("192.168.1.5", 4201))
        protocol.datagram_received(discovery_module._DISCOVERY_RESPONSE_PREFIX + b"payload", ("192.168.1.5", 4201))
        protocol.datagram_received(discovery_module._DISCOVERY_RESPONSE_PREFIX, ("192.168.1.5", 4201))
        protocol.error_received(OSError("udp error"))
        self.assertEqual(protocol.printers, {"192.168.1.5"})
        self.assertEqual(str(protocol.transport_errors[0]), "udp error")

    def test_network_errors_and_interface_filters(self):
        with self.assertRaises(discovery_module.ZebraDiscoveryNetworkError):
            self._run_discovery([], _FakeDiscoveryLoop(), adapter_error=HomeAssistantError("network"))
        invalid = [{"enabled": False, "ipv4": [{"address": "192.168.1.2", "network_prefix": 24}]}, {"enabled": True, "ipv4": [
            {}, {"address": "192.168.1.2", "network_prefix": "bad"},
            {"address": "2001:db8::1", "network_prefix": 64},
            {"address": "192.168.1.2", "network_prefix": 31},
            {"address": "127.0.0.1", "network_prefix": 8},
            {"address": "169.254.1.2", "network_prefix": 16},
            {"address": "224.0.0.1", "network_prefix": 4},
        ]}]
        with self.assertRaises(discovery_module.ZebraDiscoveryNoInterfacesError):
            self._run_discovery(invalid, _FakeDiscoveryLoop())
        adapters = [{"enabled": True, "ipv4": [{"address": "192.168.4.10", "network_prefix": 24}, {"address": "192.168.4.10", "network_prefix": 24}]}]
        loop = _FakeDiscoveryLoop(replies=("192.168.4.20", "192.168.4.5"))
        self.assertEqual(self._run_discovery(adapters, loop), ["192.168.4.20", "192.168.4.5"])
        self.assertEqual(len(loop.transports[0].sent), 9)
        self.assertTrue(loop.transports[0].closed)
        self.assertTrue(all(call[1] for call in loop.bind_calls))

    def test_transport_failure_paths_and_cleanup(self):
        adapters = [{"enabled": True, "ipv4": [{"address": "10.0.0.2", "network_prefix": 24}]}]
        bind_loop = _FakeDiscoveryLoop(bind_errors={"10.0.0.2": OSError("bind failed")})
        with self.assertRaises(discovery_module.ZebraDiscoveryTransportError):
            self._run_discovery(adapters, bind_loop)
        send_loop = _FakeDiscoveryLoop(send_error=OSError("send failed"))
        with self.assertRaisesRegex(discovery_module.ZebraDiscoveryTransportError, "could not send"):
            self._run_discovery(adapters, send_loop)
        self.assertTrue(send_loop.transports[0].closed)

        partial_adapters = [{"enabled": True, "ipv4": [
            {"address": "10.0.0.2", "network_prefix": 24},
            {"address": "10.0.1.2", "network_prefix": 24},
        ]}]
        partial_loop = _FakeDiscoveryLoop(bind_errors={"10.0.0.2": OSError("one bind failed")})
        with self.assertRaisesRegex(discovery_module.ZebraDiscoveryTransportError, "every eligible"):
            self._run_discovery(partial_adapters, partial_loop)
        self.assertTrue(partial_loop.transports[0].closed)

        protocol_loop = _FakeDiscoveryLoop(protocol_error=OSError("socket error"))
        with self.assertRaisesRegex(discovery_module.ZebraDiscoveryTransportError, "every eligible"):
            self._run_discovery(adapters, protocol_loop)
        self.assertTrue(protocol_loop.transports[0].closed)

        empty_loop = _FakeDiscoveryLoop()
        self.assertEqual(self._run_discovery(adapters, empty_loop), [])
        self.assertTrue(empty_loop.transports[0].closed)
class RemainingSmallCoverageTest(unittest.TestCase):
    def test_media_button_actions_success_and_connection_failures(self):
        coordinator = controls.FakeCoordinator({})
        coordinator.client.calibrate_media = AsyncMock()
        coordinator.client.send_print_job = AsyncMock()
        hass = SimpleNamespace(data={controls.const_module.DOMAIN: {"test_entry": coordinator}})
        entities = []
        asyncio.run(controls.button_module.async_setup_entry(hass, controls._entry(), entities.extend))
        calibration = next(entity for entity in entities if isinstance(entity, controls.button_module.ZebraMediaCalibration))
        test_print = next(entity for entity in entities if isinstance(entity, controls.button_module.ZebraTestPrint))
        asyncio.run(calibration.async_press())
        asyncio.run(test_print.async_press())
        coordinator.client.calibrate_media.assert_awaited_once()
        coordinator.client.send_print_job.assert_awaited_once_with(test_print._TEST_LABEL_ZPL)
        self.assertEqual(coordinator.refresh_count, 2)
        coordinator.client.calibrate_media.side_effect = controls.api_module.ZebraConnectionError("offline")
        with self.assertRaises(HomeAssistantError) as raised:
            asyncio.run(calibration.async_press())
        self.assertEqual(raised.exception.translation_key, "media_calibration_failed")
        coordinator.client.send_print_job.side_effect = controls.api_module.ZebraConnectionError("offline")
        with self.assertRaises(HomeAssistantError) as raised:
            asyncio.run(test_print.async_press())
        self.assertEqual(raised.exception.translation_key, "test_print_failed")
        self.assertEqual(coordinator.refresh_count, 2)

    def test_status_unspecified_flags_and_ribbon_absence(self):
        status = controls.const_module.parse_operating_status("0,1,0,0,0,0,0")
        self.assertEqual(status.errors, ("Unspecified printer error",))
        status = controls.const_module.parse_operating_status("0,0,0,0,1,0,0")
        self.assertEqual(status.warnings, ("Unspecified printer warning",))
        self.assertIsNone(controls.const_module.parse_ribbon_cartridge_inserted(None))
        self.assertIsNone(controls.const_module.parse_ribbon_cartridge_inserted("unknown"))
        self.assertTrue(controls.const_module.parse_ribbon_cartridge_inserted("yes"))
        self.assertFalse(controls.const_module.parse_ribbon_cartridge_inserted("no"))

    def test_discovered_model_helpers(self):
        flow = config_flow_module.ZebraPrinterConfigFlow()
        flow._async_get_printer_info = AsyncMock(return_value=("ZD420", "serial"))
        self.assertEqual(asyncio.run(flow._async_get_printer_model("host", 9100)), "ZD420")
        self.assertEqual(asyncio.run(flow._async_discovered_model("host")), "ZD420")
        flow._async_get_printer_model = AsyncMock(side_effect=ZebraConnectionError("offline"))
        self.assertIsNone(asyncio.run(flow._async_discovered_model("offline")))
def _valid_printer_values(**updates):
    values = {variable: "value" for variable in integration_module.VARIABLES.values()}
    values.update({
        "device.product_name": "ZD420",
        "odometer.total_label_count": "42",
        "odometer.user_label_count1": "4",
        "odometer.user_label_count2": "5",
        "odometer.total_print_length": "123 INCHES",
        "ezpl.print_method": "direct thermal",
        "device.feature.ribbon_cartridge": "present",
        "sensor.head.temp_celsius": "42.5",
        "zpl.system_status": "0,0,0,0,0,0,0",
        "device.printhead.odometer": "321",
        "print.tone": "12.5",
        "media.speed": "4",
        "ezpl.media_type": '"gap/web"',
        "head.resolution.in_dpi": "203",
        "ribbon.ribbon_low.warning": "10",
        "ribbon.cartridge.inserted": "yes",
        "ribbon.cartridge.length_remaining": "55.5",
    })
    values.update(updates)
    return values


class CoordinatorCoverageTest(unittest.TestCase):
    def _coordinator(self, values=None, errors=None):
        return integration_module.ZebraCoordinator(
            SimpleNamespace(), _SgdClient(values or _valid_printer_values(), errors)
        )

    def test_required_and_optional_variable_read_errors(self):
        coordinator = self._coordinator()
        errors = []
        self.assertEqual(asyncio.run(coordinator._async_read_variable("optional", "missing", errors)), None)
        self.assertEqual(errors, [])
        self.assertIsNone(asyncio.run(coordinator._async_read_variable("missing", "missing", errors)))
        self.assertEqual(errors, [])
        coordinator.client.errors["optional"] = integration_module.ZebraConnectionError("optional offline")
        self.assertIsNone(asyncio.run(coordinator._async_read_variable("optional", "optional", errors)))
        self.assertEqual(errors, ["optional"])
        coordinator.client.errors["required"] = integration_module.ZebraConnectionError("required offline")
        with self.assertRaises(integration_module.ZebraConnectionError):
            asyncio.run(coordinator._async_read_variable("required", "required", errors, required=True))
        self.assertEqual(coordinator.last_communication_error, "Could not read required printer value: required")
        del coordinator.client.errors["required"]
        with self.assertRaisesRegex(integration_module.ZebraConnectionError, "unavailable"):
            asyncio.run(coordinator._async_read_variable("required", "missing", errors, required=True))
        self.assertEqual(coordinator.last_communication_error, "Required printer value required is unavailable")

    def test_update_data_normalizes_supported_printer_values(self):
        coordinator = self._coordinator()
        data = asyncio.run(coordinator._async_update_data())
        self.assertEqual(data["total_labels"], 42)
        self.assertEqual(data["resettable_labels_1"], 4)
        self.assertEqual(data["total_print_length"], 123)
        self.assertEqual(data["printhead_usage"], 321)
        self.assertEqual(data["print_tone"], 12.5)
        self.assertEqual(data["print_speed"], 4)
        self.assertEqual(data["print_speed_max"], 6)
        self.assertEqual(data["media_type"], "gap/notch")
        self.assertEqual(data["printhead_temperature"], 42.5)
        self.assertTrue(data["ribbon_cartridge_capable"])
        self.assertTrue(data["ribbon_inserted"])
        self.assertEqual(data["ribbon_low_warning"], "10")
        self.assertEqual(data["ribbon_remaining"], 55.5)
        self.assertEqual(data["operating_status"], "Ready")
        self.assertEqual(data["optional_read_errors"], [])
        self.assertIsNone(coordinator.last_communication_error)

    def test_update_data_optional_ribbon_and_sensor_paths(self):
        cases = [
            ({"device.feature.ribbon_cartridge": "not present", "ribbon.cartridge.inserted": "no"}, True, False),
            ({"device.feature.ribbon_cartridge": "unsupported"}, False, None),
            ({"device.feature.ribbon_cartridge": None}, False, None),
            ({"device.feature.ribbon_cartridge": "present", "ribbon.ribbon_low.warning": "unsupported", "ribbon.cartridge.length_remaining": "bad"}, True, True),
            ({"device.feature.ribbon_cartridge": "present", "ribbon.cartridge.length_remaining": "-1"}, True, True),
            ({"device.feature.ribbon_cartridge": "present", "ribbon.cartridge.length_remaining": "75"}, True, True),
            ({"device.feature.ribbon_cartridge": "present", "ribbon.cartridge.length_remaining": "nan"}, True, True),
        ]
        for updates, capable, inserted in cases:
            with self.subTest(updates=updates):
                data = asyncio.run(self._coordinator(_valid_printer_values(**updates))._async_update_data())
                self.assertEqual(data["ribbon_cartridge_capable"], capable)
                self.assertEqual(data["ribbon_inserted"], inserted)
                if updates.get("ribbon.ribbon_low.warning") == "unsupported":
                    self.assertIsNone(data["ribbon_low_warning"])
                if "ribbon.cartridge.length_remaining" in updates and updates["ribbon.cartridge.length_remaining"] != "55.5":
                    self.assertIsNone(data["ribbon_remaining"])
        no_inserted_cartridge = _valid_printer_values(**{
            "ribbon.cartridge.inserted": "no",
            "ribbon.cartridge.length_remaining": "0",
        })
        data = asyncio.run(self._coordinator(no_inserted_cartridge)._async_update_data())
        self.assertFalse(data["ribbon_inserted"])
        self.assertIsNone(data["ribbon_remaining"])
        unknown_inserted_status = _valid_printer_values(**{
            "ribbon.cartridge.inserted": "unknown",
        })
        data = asyncio.run(self._coordinator(unknown_inserted_status)._async_update_data())
        self.assertIsNone(data["ribbon_inserted"])
        self.assertIsNone(data["ribbon_remaining"])
        no_ribbon = _valid_printer_values(**{"device.feature.ribbon_cartridge": "unsupported"})
        coordinator = self._coordinator(no_ribbon, {"device.printhead.odometer": integration_module.ZebraConnectionError("optional")})
        data = asyncio.run(coordinator._async_update_data())
        self.assertEqual(data["optional_read_errors"], ["printhead_usage"])
        self.assertIsNone(data["printhead_usage"])

    def test_update_data_invalid_optional_values_and_required_failures(self):
        invalid_cases = [
            {"odometer.user_label_count1": "bad", "odometer.user_label_count2": "-1", "odometer.total_print_length": "bad", "device.printhead.odometer": "-1"},
            {"print.tone": "bad", "media.speed": "2.5", "head.resolution.in_dpi": "203.5", "ezpl.media_type": "unknown", "sensor.head.temp_celsius": "inf", "zpl.system_status": 123},
            {"print.tone": "nan", "media.speed": "99", "head.resolution.in_dpi": "600", "sensor.head.temp_celsius": "bad"},
            {"print.tone": "31", "media.speed": "4", "head.resolution.in_dpi": "300", "sensor.head.temp_celsius": "-inf"},
        ]
        for updates in invalid_cases:
            with self.subTest(updates=updates):
                data = asyncio.run(self._coordinator(_valid_printer_values(**updates))._async_update_data())
                optional_value_keys = (
                ("odometer.user_label_count1", "resettable_labels_1"),
                ("odometer.user_label_count2", "resettable_labels_2"),
                ("odometer.total_print_length", "total_print_length"),
                ("device.printhead.odometer", "printhead_usage"),
                ("print.tone", "print_tone"),
                ("ezpl.media_type", "media_type"),
                ("sensor.head.temp_celsius", "printhead_temperature"),
                ("zpl.system_status", "operating_status"),
            )
            for variable, key in optional_value_keys:
                if variable in updates:
                    self.assertIsNone(data[key])
            if "media.speed" in updates:
                if updates["media.speed"] == "4":
                    self.assertEqual(data["print_speed"], 4)
                else:
                    self.assertIsNone(data["print_speed"])
        bad_speed = asyncio.run(self._coordinator(_valid_printer_values(**{"media.speed": "bad"}))._async_update_data())
        self.assertIsNone(bad_speed["print_speed"])
        invalid_counter = self._coordinator(_valid_printer_values(**{"odometer.total_label_count": "bad"}))
        with self.assertRaises(update_coordinator.UpdateFailed):
            asyncio.run(invalid_counter._async_update_data())
        negative_counter = self._coordinator(_valid_printer_values(**{"odometer.total_label_count": "-1"}))
        with self.assertRaises(update_coordinator.UpdateFailed):
            asyncio.run(negative_counter._async_update_data())
        for required in ("odometer.total_label_count", "ezpl.print_method"):
            client = _SgdClient(_valid_printer_values(), {required: integration_module.ZebraConnectionError("offline")})
            with self.assertRaises(update_coordinator.UpdateFailed):
                asyncio.run(integration_module.ZebraCoordinator(SimpleNamespace(), client)._async_update_data())
        with self.assertRaises(update_coordinator.UpdateFailed):
            asyncio.run(self._coordinator(_valid_printer_values(**{"odometer.total_label_count": None}))._async_update_data())

    def test_update_data_print_speed_resolution_and_status_branches(self):
        data = asyncio.run(self._coordinator(_valid_printer_values(**{"head.resolution.in_dpi": "300", "media.speed": "4", "ezpl.media_type": "gap/notch", "zpl.system_status": "0,1,0,0,1,0,0"}))._async_update_data())
        self.assertEqual(data["print_speed_max"], 4)
        self.assertEqual(data["print_speed"], 4)
        self.assertEqual(data["media_type"], "gap/notch")
        self.assertEqual(data["operating_status"], "Unspecified printer error")
        self.assertEqual(data["status_warnings"], ["Unspecified printer warning"])
        data = asyncio.run(self._coordinator(_valid_printer_values(**{"head.resolution.in_dpi": "203", "media.speed": "6.5", "zpl.system_status": "bad"}))._async_update_data())
        self.assertEqual(data["print_speed_max"], 6)
        self.assertIsNone(data["print_speed"])
        self.assertIsNone(data["operating_status"])
        self.assertIsNone(data["status_paused"])
        self.assertIsNone(data["status_errors"])
        self.assertIsNone(data["status_warnings"])
class IntegrationLifecycleCoverageTest(unittest.TestCase):
    def _entry(self, *, options=None, host="printer.local", port=9100, unique_id=None):
        return SimpleNamespace(
            entry_id="entry-1", unique_id=unique_id,
            data={"host": host, "port": port}, options=dict(options or {}),
            async_on_unload=Mock(), add_update_listener=Mock(return_value="listener"),
        )

    def _hass(self):
        return SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
                async_reload=AsyncMock(),
            ),
        )

    def test_component_setup_registers_services(self):
        hass = self._hass()
        with patch.object(integration_module, "async_setup_services") as setup_services:
            self.assertTrue(asyncio.run(integration_module.async_setup(hass, {})))
        setup_services.assert_called_once_with(hass)

    def test_entry_setup_without_stable_identity_or_alerts(self):
        hass = self._hass()
        entry = self._entry(
            options=_alert_options(
                **{alerts_module.CONF_ALERTS_ENABLED: False}
            )
        )
        client = _SgdClient(_valid_printer_values())
        client.host, client.port = entry.data["host"], entry.data["port"]
        with (
            patch.object(integration_module, "ZebraClient", return_value=client),
            patch.object(
                integration_module,
                "async_migrate_config_entry_identity",
            ) as migrate,
            patch.object(
                integration_module,
                "async_register_webhook",
                new=AsyncMock(),
            ) as register,
            patch.object(
                integration_module,
                "async_configure_printer_alerts",
                new=AsyncMock(),
            ) as configure,
        ):
            self.assertTrue(asyncio.run(integration_module.async_setup_entry(hass, entry)))
        coordinator = hass.data[integration_module.DOMAIN][entry.entry_id]
        self.assertEqual(coordinator.data["total_labels"], 42)
        self.assertIsNone(coordinator.alert_configuration)
        migrate.assert_not_called()
        register.assert_not_awaited()
        configure.assert_not_awaited()
        entry.async_on_unload.assert_called_once_with("listener")
        entry.add_update_listener.assert_called_once()
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            entry, integration_module.PLATFORMS
        )
    def test_entry_setup_stable_identity_and_alert_configuration_outcomes(self):
        options = _alert_options()
        entry = self._entry(options=options)
        hass = self._hass()
        client = _SgdClient(_valid_printer_values(**{"device.unique_id": " stable-id "}))
        client.host, client.port = entry.data["host"], entry.data["port"]
        config_type = integration_module.ZebraAlertConfiguration
        with patch.object(integration_module, "ZebraClient", return_value=client), patch.object(integration_module, "async_migrate_config_entry_identity") as migrate, patch.object(integration_module, "async_register_webhook", new=AsyncMock()) as register, patch.object(integration_module, "async_configure_printer_alerts", new=AsyncMock()) as configure:
            self.assertTrue(asyncio.run(integration_module.async_setup_entry(hass, entry)))
        migrate.assert_called_once_with(hass, entry, "zebra-unique:stable-id")
        register.assert_awaited_once()
        configure.assert_awaited_once_with(client, unittest.mock.ANY)
        coordinator = hass.data[integration_module.DOMAIN][entry.entry_id]
        self.assertIsInstance(coordinator.alert_configuration, config_type)

        for failure in (integration_module.ZebraConnectionError("offline"), ValueError("unsupported")):
            with self.subTest(failure=type(failure).__name__):
                hass = self._hass()
                entry = self._entry(options=options)
                client = _SgdClient(_valid_printer_values(), {"device.unique_id": integration_module.ZebraConnectionError("identity")})
                client.host, client.port = entry.data["host"], entry.data["port"]
                with patch.object(integration_module, "ZebraClient", return_value=client), patch.object(integration_module, "async_register_webhook", new=AsyncMock()), patch.object(integration_module, "async_configure_printer_alerts", new=AsyncMock(side_effect=failure)):
                    self.assertTrue(asyncio.run(integration_module.async_setup_entry(hass, entry)))
                self.assertIsNotNone(hass.data[integration_module.DOMAIN][entry.entry_id].alert_configuration)

    def test_unload_success_failure_missing_configuration_and_platform_failure(self):
        entry = self._entry(options=_alert_options())
        config = integration_module.configuration_from_options(entry.options)
        client = _SgdClient(_valid_printer_values())
        coordinator = SimpleNamespace(alert_configuration=config, client=client)
        hass = self._hass()
        hass.data = {integration_module.DOMAIN: {entry.entry_id: coordinator}}
        with patch.object(integration_module, "async_unregister_webhook") as unregister, patch.object(integration_module, "async_remove_printer_alerts", new=AsyncMock()) as remove:
            self.assertTrue(asyncio.run(integration_module.async_unload_entry(hass, entry)))
        unregister.assert_called_once_with(hass, config)
        remove.assert_awaited_once_with(client, config)
        self.assertNotIn(entry.entry_id, hass.data[integration_module.DOMAIN])

        for failure in (integration_module.ZebraConnectionError("offline"),):
            hass = self._hass()
            hass.data = {integration_module.DOMAIN: {entry.entry_id: coordinator}}
            with patch.object(integration_module, "async_unregister_webhook"), patch.object(integration_module, "async_remove_printer_alerts", new=AsyncMock(side_effect=failure)):
                self.assertTrue(asyncio.run(integration_module.async_unload_entry(hass, entry)))
        hass = self._hass()
        hass.data = {integration_module.DOMAIN: {entry.entry_id: SimpleNamespace(alert_configuration=None)}}
        self.assertTrue(asyncio.run(integration_module.async_unload_entry(hass, entry)))
        hass.config_entries.async_unload_platforms.return_value = False
        hass.data = {integration_module.DOMAIN: {entry.entry_id: coordinator}}
        self.assertFalse(asyncio.run(integration_module.async_unload_entry(hass, entry)))
        self.assertIn(entry.entry_id, hass.data[integration_module.DOMAIN])

    def test_remove_entry_loaded_unconfigured_and_alert_paths(self):
        entry = self._entry(options=_alert_options())
        hass = self._hass()
        hass.data = {integration_module.DOMAIN: {entry.entry_id: object()}}
        with patch.object(integration_module, "ZebraClient") as client_factory:
            asyncio.run(integration_module.async_remove_entry(hass, entry))
        client_factory.assert_not_called()

        hass.data = {}
        entry.options = {}
        with patch.object(integration_module, "ZebraClient") as client_factory:
            asyncio.run(integration_module.async_remove_entry(hass, entry))
        client_factory.assert_not_called()

        entry.options = _alert_options()
        client = _SgdClient()
        with patch.object(integration_module, "ZebraClient", return_value=client), patch.object(integration_module, "async_unregister_webhook") as unregister, patch.object(integration_module, "async_remove_printer_alerts", new=AsyncMock()) as remove:
            asyncio.run(integration_module.async_remove_entry(hass, entry))
        unregister.assert_called_once()
        remove.assert_awaited_once()
        with patch.object(integration_module, "ZebraClient", return_value=client), patch.object(integration_module, "async_unregister_webhook"), patch.object(integration_module, "async_remove_printer_alerts", new=AsyncMock(side_effect=integration_module.ZebraConnectionError("offline"))):
            asyncio.run(integration_module.async_remove_entry(hass, entry))

    def test_reload_entry_changed_fields_and_refresh(self):
        entry = self._entry()
        client = SimpleNamespace(host="printer.local", port=9100)
        coordinator = SimpleNamespace(client=client, alert_configuration=None, async_request_refresh=AsyncMock())
        hass = self._hass()
        hass.data = {integration_module.DOMAIN: {entry.entry_id: coordinator}}
        asyncio.run(integration_module._async_reload_entry(hass, entry))
        coordinator.async_request_refresh.assert_awaited_once()
        hass.data = {integration_module.DOMAIN: {}}
        asyncio.run(integration_module._async_reload_entry(hass, entry))
        hass.config_entries.async_reload.assert_not_awaited()

        for changed in (
            self._entry(host="other.local"),
            self._entry(port=9200),
            self._entry(options=_alert_options()),
        ):
            changed.entry_id = entry.entry_id
            with self.subTest(changed=changed.data, options=changed.options):
                hass.data = {integration_module.DOMAIN: {entry.entry_id: coordinator}}
                hass.config_entries.async_reload.reset_mock()
                asyncio.run(integration_module._async_reload_entry(hass, changed))
                hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
