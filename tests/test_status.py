"""Verify Zebra's combined pause, error, and warning status flags."""

import importlib.util
from pathlib import Path
import sys
import unittest


CONST_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "zebra_printer" / "const.py"
SPEC = importlib.util.spec_from_file_location("zebra_const_under_test", CONST_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
parse = MODULE.parse_operating_status


class PrinterStatusTest(unittest.TestCase):
    def test_ready(self):
        status = parse("0,0,00000000,00000000,0,00000000,00000000")
        self.assertEqual(status.state, "Ready")
        self.assertFalse(status.paused)
        self.assertEqual(status.errors, ())

    def test_pause_only(self):
        status = parse("1,1,00000000,00010000,0,00000000,00000000")
        self.assertEqual(status.state, "Paused")
        self.assertTrue(status.paused)
        self.assertEqual(status.errors, ())

    def test_multiple_errors_and_pause(self):
        status = parse("1,1,00000000,00010005,0,00000000,00000000")
        self.assertEqual(status.state, "Media out")
        self.assertTrue(status.paused)
        self.assertEqual(status.errors, ("Media out", "Head open"))

    def test_warning_and_unknown_flags(self):
        status = parse("0,0,00000000,00000000,1,00000000,80000003")
        self.assertEqual(status.state, "Media calibration needed")
        self.assertIn("Clean printhead", status.warnings)
        self.assertIn("Unknown warning flags: 0x0000000080000000", status.warnings)

    def test_every_documented_error_flag(self):
        for bit, label in MODULE.ERROR_FLAGS.items():
            with self.subTest(bit=bit, label=label):
                status = parse(f"0,1,00000000,{1 << bit:08X},0,00000000,00000000")
                self.assertEqual(status.state, label)
                self.assertEqual(status.errors, (label,))

    def test_every_documented_warning_flag(self):
        for bit, label in MODULE.WARNING_FLAGS.items():
            with self.subTest(bit=bit, label=label):
                status = parse(f"0,0,00000000,00000000,1,00000000,{1 << bit:08X}")
                self.assertEqual(status.state, label)
                self.assertEqual(status.warnings, (label,))

    def test_malformed_response(self):
        self.assertIsNone(parse(None))
        self.assertIsNone(parse("?"))
        self.assertIsNone(parse("0,0,NOT_HEX,00000000,0,00000000,00000000"))


if __name__ == "__main__":
    unittest.main()
