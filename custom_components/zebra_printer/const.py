"""Constants and Zebra system-status decoding."""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "zebra_printer"
DEFAULT_PORT = 9100
POLL_SECONDS = 60

DIRECT_THERMAL = "Direct Thermal"
THERMAL_TRANSFER = "Thermal Transfer"
METHOD_VALUES = {
    DIRECT_THERMAL: "direct thermal",
    THERMAL_TRANSFER: "thermal transfer",
}


@dataclass(frozen=True)
class PrinterStatus:
    """Decoded printer status and every reported condition."""

    state: str
    paused: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    raw: str


# Group 1 bits from Zebra's zpl.system_status / ~HQES tables. Higher bits
# marked by Zebra as KR403-only are included for models that report them.
ERROR_FLAGS = {
    0: "Media out",
    1: "Ribbon out",
    2: "Head open",
    3: "Cutter fault",
    4: "Printhead over temperature",
    5: "Motor over temperature",
    6: "Bad printhead element",
    7: "Printhead detection error",
    8: "Invalid firmware configuration",
    9: "Printhead thermistor open",
    12: "Paper jam during retract",
    13: "Presenter not running",
    14: "Paper feed error",
    15: "Clear paper path failed",
    17: "Retract timed out",
    18: "Black mark calibration error",
    19: "Black mark not found",
}

WARNING_FLAGS = {
    0: "Media calibration needed",
    1: "Clean printhead",
    2: "Replace printhead",
    3: "Paper near end",
    4: "Sensor 1: paper before head",
    5: "Sensor 2: black mark",
    6: "Sensor 3: paper after head",
    7: "Sensor 4: loop ready",
    8: "Sensor 5: presenter",
    9: "Sensor 6: retract ready",
    10: "Sensor 7: in retract",
    11: "Sensor 8: at bin",
}


def _conditions(group: int, known: dict[int, str], kind: str) -> tuple[str, ...]:
    """Name all set bits, retaining unknown bits as hexadecimal flags."""
    values = [name for bit, name in known.items() if group & (1 << bit)]
    unknown = group & ~sum(1 << bit for bit in known)
    if unknown:
        values.append(f"Unknown {kind} flags: 0x{unknown:016X}")
    return tuple(values)


def parse_operating_status(value: str | None) -> PrinterStatus | None:
    """Decode all pause, error, and warning flags in zpl.system_status."""
    if not value:
        return None
    fields = [part.strip() for part in value.strip().strip('"').split(",")]
    if len(fields) != 7 or any(fields[i] not in ("0", "1") for i in (0, 1, 4)):
        return None
    try:
        error_bits = (int(fields[2], 16) << 32) | int(fields[3], 16)
        warning_bits = (int(fields[5], 16) << 32) | int(fields[6], 16)
    except ValueError:
        return None

    paused = fields[0] == "1" or bool(error_bits & (1 << 16))
    errors = list(_conditions(error_bits & ~(1 << 16), ERROR_FLAGS, "error"))
    warnings = list(_conditions(warning_bits, WARNING_FLAGS, "warning"))
    if fields[1] == "1" and not errors and not paused:
        errors.append("Unspecified printer error")
    if fields[4] == "1" and not warnings:
        warnings.append("Unspecified printer warning")

    state = errors[0] if errors else "Paused" if paused else warnings[0] if warnings else "Ready"
    return PrinterStatus(state, paused, tuple(errors), tuple(warnings), value)
