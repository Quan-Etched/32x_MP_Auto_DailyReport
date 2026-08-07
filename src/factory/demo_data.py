"""Synthetic run table with the same shape the collector produces.

Purpose: make the dashboard runnable and reviewable without an API key, and give
the metrics layer a fixture with known-interesting structure — a two-shift day, a
station that degrades, a failure burst, and a handful of repeat-offender DUTs.

This is clearly labelled as demo data everywhere it surfaces (``source: "demo"``
puts a banner on the dashboard) so it can never be mistaken for factory output.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from . import config
from .collect import _mark_attempts
from .parse import summarize_tests

STATIONS = ["ST-01", "ST-02", "ST-03", "ST-04", "ST-05"]

TESTS = [
    ("CHK_BIOS_BOOT_ORDER", 0.010),
    ("CHK_PCIE_LINK_WIDTH", 0.022),
    ("CHK_DRAM_TRAINING", 0.014),
    ("CHK_THERMAL_RAMP", 0.030),
    ("CHK_POWER_RAILS", 0.008),
    ("CHK_FAN_CURVE", 0.006),
    ("CHK_NIC_LOOPBACK", 0.012),
    ("CHK_FW_VERSION", 0.004),
    ("CHK_CLOCK_TREE", 0.009),
    ("CHK_SMBUS_SCAN", 0.005),
    ("CHK_MEM_BANDWIDTH", 0.016),
    ("CHK_LINK_TRAINING_RETRY", 0.020),
]

CODES = {
    "CHK_PCIE_LINK_WIDTH": ["E_LINK_X8_EXPECTED_X16", "E_LTSSM_TIMEOUT"],
    "CHK_THERMAL_RAMP": ["E_TJ_OVER_LIMIT", "E_RAMP_TOO_SLOW"],
    "CHK_DRAM_TRAINING": ["E_TRAIN_FAIL_CH2", "E_ECC_UNCORRECTABLE"],
    "CHK_BIOS_BOOT_ORDER": ["E_BOOT_DEV_MISSING"],
}


def generate(
    days: int = 2,
    level: str = "l10",
    suite: str = "L10_tests",
    version: str = "2026.214.0-gita7f2fadc",
    seed: int = 7,
    end: datetime = None,
) -> Dict[str, Any]:
    """Build a demo payload matching ``collect.collect()``'s output shape."""
    rng = random.Random(seed)
    tz = _tzinfo()
    end_local = (end or datetime.now(tz)).replace(minute=0, second=0, microsecond=0)
    start_local = end_local - timedelta(days=days)

    records: List[Dict[str, Any]] = []
    dut_counter = 0
    repeat_offenders: List[str] = []

    cursor = start_local
    while cursor < end_local:
        hour = cursor.hour
        # Two shifts: 06:00-14:00 ramps, 14:00-22:00 is peak, nights are skeleton crew.
        if 6 <= hour < 14:
            base_rate = 7
        elif 14 <= hour < 22:
            base_rate = 10
        else:
            base_rate = 2
        # A thermal-chamber problem on ST-03 during the second day's afternoon.
        burst = (cursor - start_local) > timedelta(days=1) and 15 <= hour < 19

        count = max(0, int(rng.gauss(base_rate, 1.6)))
        for _ in range(count):
            station = rng.choice(STATIONS)
            if repeat_offenders and rng.random() < 0.18:
                dut = rng.choice(repeat_offenders)
            else:
                dut_counter += 1
                dut = "2676944{:05d}".format(10000 + dut_counter)

            started = cursor + timedelta(
                minutes=rng.uniform(0, 59), seconds=rng.uniform(0, 59)
            )
            tests, duration = _run_tests(rng, station, burst)
            status = "pass"
            if any(test["status"] in ("fail", "error") for test in tests):
                status = "error" if rng.random() < 0.12 else "fail"

            if status != "pass" and rng.random() < 0.35 and len(repeat_offenders) < 14:
                repeat_offenders.append(dut)

            run_id = "{}_{}_{}".format(
                suite, version, started.strftime("%Y%m%d_%H%M%S")
            )
            records.append(
                {
                    "runId": run_id,
                    "level": level,
                    "dutSerial": dut,
                    "station": station,
                    "suite": suite,
                    "version": version,
                    "startTs": int(started.astimezone(timezone.utc).timestamp()),
                    "endTs": int(
                        (started + timedelta(seconds=duration))
                        .astimezone(timezone.utc)
                        .timestamp()
                    ),
                    "durationSec": round(duration, 1),
                    "status": status,
                    "startFromRunId": False,
                    "tests": tests,
                }
            )
        cursor += timedelta(hours=1)

    records.sort(key=lambda rec: rec["startTs"])
    _mark_attempts(records)
    for record in records:
        summarize_tests(record)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "window": {
            "from": start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "levels": [level],
        "timezone": config.timezone_name(),
        "runCount": len(records),
        "problems": [],
        "source": "demo",
        "runs": records,
    }


def _run_tests(rng: random.Random, station: str, burst: bool):
    """Simulate one run's test list and total duration."""
    tests = []
    total = 0.0
    for name, base_fail in TESTS:
        rate = base_fail
        if burst and station == "ST-03" and name == "CHK_THERMAL_RAMP":
            rate = 0.55
        elif station == "ST-05":
            rate = base_fail * 1.9  # a station that has been drifting
        duration = max(1.0, rng.gauss(38, 12))
        failed = rng.random() < rate
        total += duration
        tests.append(
            {
                "name": name,
                "status": "fail" if failed else "pass",
                "durationSec": round(duration, 1),
                "logFile": "artifacts/{}/iteration_1/{}.log".format(name, name.lower()),
                "code": rng.choice(CODES[name]) if failed and name in CODES else (
                    "E_ASSERT" if failed else None
                ),
            }
        )
        if failed and rng.random() < 0.4:
            break  # suite aborts on some failures
    return tests, total + rng.uniform(20, 90)  # fixture load/unload overhead


def _tzinfo():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(config.timezone_name())
    except Exception:  # noqa: BLE001
        return timezone.utc
