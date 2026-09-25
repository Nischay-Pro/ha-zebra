"""Test the safety and command mapping of Zebra control entities."""

import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_PATH = ROOT / "custom_components" / "zebra_printer"


def _module(name, *, package=False):
    """Install a small Home Assistant stub module for entity unit tests."""
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    sys.modules[name] = module
    return module


def _install_homeassistant_stubs():
    ha = _module("homeassistant", package=True)
    components = _module("homeassistant.components", package=True)
    helpers = _module("homeassistant.helpers", package=True)
    config_entries = _module("homeassistant.config_entries")
    const = _module("homeassistant.const")
    core = _module("homeassistant.core")
    exceptions = _module("homeassistant.exceptions")
    button = _module("homeassistant.components.button")
    select = _module("homeassistant.components.select")
    entity = _module("homeassistant.helpers.entity")
    entity_platform = _module("homeassistant.helpers.entity_platform")
    update_coordinator = _module("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

    class HomeAssistantError(Exception):
        def __init__(
            self,
            *args,
            translation_domain=None,
            translation_key=None,
            translation_placeholders=None,
        ):
            super().__init__(*args)
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders

    config_entries.ConfigEntry = type("ConfigEntry", (), {})
    const.EntityCategory = SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic")
    core.HomeAssistant = type("HomeAssistant", (), {})
    exceptions.HomeAssistantError = HomeAssistantError
    button.ButtonEntity = type("ButtonEntity", (), {})
    select.SelectEntity = type("SelectEntity", (), {})
    entity.DeviceInfo = lambda **kwargs: kwargs
    entity_platform.AddConfigEntryEntitiesCallback = object
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    custom_components = _module("custom_components", package=True)
    custom_components.__path__ = [str(ROOT / "custom_components")]
    integration = _module("custom_components.zebra_printer", package=True)
    integration.__path__ = [str(INTEGRATION_PATH)]
    integration.ZebraCoordinator = type("ZebraCoordinator", (), {})
    return HomeAssistantError


HomeAssistantError = _install_homeassistant_stubs()
button_module = importlib.import_module("custom_components.zebra_printer.button")
select_module = importlib.import_module("custom_components.zebra_printer.select")
api_module = importlib.import_module("custom_components.zebra_printer.api")
const_module = importlib.import_module("custom_components.zebra_printer.const")


class FakeClient:
    def __init__(self, values=None, *, fail_write=False):
        self.values = values or {}
        self.fail_write = fail_write
        self.get_calls = []
        self.set_calls = []

    async def get(self, variable):
        self.get_calls.append(variable)
        return self.values.get(variable)

    async def set(self, variable, value):
        self.set_calls.append((variable, value))
        if self.fail_write:
            raise api_module.ZebraConnectionError("write failed")
        self.values[variable] = value


class FakeCoordinator:
    def __init__(self, data, client=None):
        self.data = data
        self.client = client or FakeClient()
        self.refresh_count = 0

    async def async_request_refresh(self):
        self.refresh_count += 1


def _entry():
    return SimpleNamespace(entry_id="test_entry", data={"host": "printer.local", "port": 9100})


class ZebraControlsTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_reset_button_targets_only_its_counter(self):
        for counter in (1, 2):
            with self.subTest(counter=counter):
                client = FakeClient()
                coordinator = FakeCoordinator({"model": "ZD420", "firmware": "test"}, client)
                entity = button_module.ZebraCounterReset(
                    coordinator, _entry(), f"reset_counter_{counter}", counter
                )

                await entity.async_press()

                self.assertEqual(
                    client.set_calls,
                    [(f"odometer.user_label_count{counter}", "0")],
                )
                self.assertEqual(coordinator.refresh_count, 1)

    async def test_counter_button_is_created_only_when_printer_reports_counter(self):
        coordinator = FakeCoordinator(
            {
                "model": "ZD420",
                "firmware": "test",
                "resettable_labels_1": 20,
                "resettable_labels_2": None,
            }
        )
        hass = SimpleNamespace(
            data={const_module.DOMAIN: {_entry().entry_id: coordinator}}
        )
        created = []

        await button_module.async_setup_entry(hass, _entry(), created.extend)

        self.assertEqual([entity.counter for entity in created], [1])

    async def test_failed_counter_reset_is_reported_without_refresh(self):
        client = FakeClient(fail_write=True)
        coordinator = FakeCoordinator({"model": "ZD420", "firmware": "test"}, client)
        entity = button_module.ZebraCounterReset(coordinator, _entry(), "reset_counter_2", 2)

        with self.assertRaises(HomeAssistantError) as raised:
            await entity.async_press()

        self.assertEqual(raised.exception.translation_key, "counter_reset_failed")
        self.assertEqual(client.set_calls, [("odometer.user_label_count2", "0")])
        self.assertEqual(coordinator.refresh_count, 0)

    async def test_direct_thermal_selection_sends_printer_value(self):
        client = FakeClient()
        coordinator = FakeCoordinator(
            {"model": "ZD420", "firmware": "test", "print_method": "thermal transfer"},
            client,
        )
        entity = select_module.ZebraPrintMethod(coordinator, _entry(), "print_method")

        self.assertEqual(entity.current_option, const_module.THERMAL_TRANSFER)
        await entity.async_select_option(const_module.DIRECT_THERMAL)

        self.assertEqual(client.set_calls, [("ezpl.print_method", "direct thermal")])
        self.assertEqual(coordinator.refresh_count, 1)

    async def test_thermal_transfer_requires_inserted_ribbon(self):
        client = FakeClient({"ribbon.cartridge.inserted": "no"})
        coordinator = FakeCoordinator({"model": "ZD420", "firmware": "test"}, client)
        entity = select_module.ZebraPrintMethod(coordinator, _entry(), "print_method")

        with self.assertRaises(HomeAssistantError) as raised:
            await entity.async_select_option(const_module.THERMAL_TRANSFER)

        self.assertEqual(raised.exception.translation_key, "ribbon_required")
        self.assertEqual(client.set_calls, [])
        self.assertEqual(coordinator.refresh_count, 0)

    async def test_thermal_transfer_with_ribbon_and_unknown_option(self):
        client = FakeClient({"ribbon.cartridge.inserted": "yes"})
        coordinator = FakeCoordinator({"model": "ZD420", "firmware": "test"}, client)
        entity = select_module.ZebraPrintMethod(coordinator, _entry(), "print_method")

        await entity.async_select_option(const_module.THERMAL_TRANSFER)
        self.assertEqual(client.set_calls, [("ezpl.print_method", "thermal transfer")])
        self.assertEqual(coordinator.refresh_count, 1)

        with self.assertRaises(HomeAssistantError) as raised:
            await entity.async_select_option("Invented Method")
        self.assertEqual(raised.exception.translation_key, "unsupported_print_method")
        self.assertEqual(len(client.set_calls), 1)

    async def test_print_method_write_failure_is_translated(self):
        client = FakeClient(fail_write=True)
        coordinator = FakeCoordinator({"model": "ZD420", "firmware": "test"}, client)
        entity = select_module.ZebraPrintMethod(coordinator, _entry(), "print_method")

        with self.assertRaises(HomeAssistantError) as raised:
            await entity.async_select_option(const_module.DIRECT_THERMAL)

        self.assertEqual(
            raised.exception.translation_key, "print_method_change_failed"
        )
        self.assertEqual(coordinator.refresh_count, 0)


class EnglishTranslationCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        translation_path = INTEGRATION_PATH / "translations" / "en.json"
        cls.translation = json.loads(translation_path.read_text(encoding="utf-8"))

    def test_all_entity_names_are_translated(self):
        expected = {
            "sensor": {
                "operating_status",
                "total_labels",
                "resettable_labels_1",
                "resettable_labels_2",
                "total_print_length",
                "firmware",
                "printhead_temperature",
                "ribbon_inserted",
                "paper_supply",
            },
            "select": {"print_method"},
            "button": {"reset_counter_1", "reset_counter_2"},
        }
        entities = self.translation["entity"]
        for platform, translation_keys in expected.items():
            with self.subTest(platform=platform):
                self.assertTrue(translation_keys <= entities[platform].keys())
                for key in translation_keys:
                    self.assertTrue(entities[platform][key].get("name"))

    def test_config_and_control_errors_have_english_messages(self):
        self.assertIn("user", self.translation["config"]["step"])
        for key in (
            "counter_reset_failed",
            "print_method_change_failed",
            "ribbon_required",
            "unsupported_print_method",
        ):
            with self.subTest(exception=key):
                self.assertTrue(self.translation["exceptions"][key]["message"])

    def test_custom_integration_uses_translations_file_not_core_strings_file(self):
        self.assertFalse((INTEGRATION_PATH / "strings.json").exists())


if __name__ == "__main__":
    unittest.main()
