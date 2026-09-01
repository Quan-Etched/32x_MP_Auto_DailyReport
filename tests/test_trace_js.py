"""dashboard/trace.js, run for real against a bundle this test builds.

WHY A JAVASCRIPT TEST IN A PYTHON SUITE
---------------------------------------
The dashboard has no build step and no JS test runner, so page modules have
historically been checked by opening them. ``trace.js`` decides what a failure
investigation is told about a serial — which records exist, and which link
reaches the raw data — and that deserves an assertion.

So: build a bundle from a synthetic snapshot with the real
``shopfloor.build_trace``, then run the real ``dashboard/trace.js`` over it under
JavaScriptCore with a DOM stub (``tests/trace_dom_harness.js``) and read the
rendered text back. End to end, Python graph → bundle → rendered page.

Skipped where ``jsc`` is absent, which is every Linux box. That is a real gap and
it is stated rather than hidden: on macOS, where this is developed, it runs.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

JSC = Path(
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
)

from shopfloor import build_trace, mirror  # noqa: E402

UNIT = "268947020002"
MODULE = "268862090001"
PV1 = "268862110000005"
SOHU = "JE60702845202602090204"


def _payload(sn, children=(), process=(), kids_meta=()):
    return {
        "serial": sn,
        "process_events": [
            {"unit_sn": sn, "process_ts": ts, "station": st, "section": sec,
             "result": res, "route": "PIW0"}
            for ts, st, sec, res in process
        ],
        "current_children": list(kids_meta),
        "current_tree": {"serial": sn, "children": list(children)},
    }


def _node(slot, sn, ctype, valid_from, children=()):
    return {"slot": slot, "serial": sn, "component_type": ctype,
            "raw_location": None, "valid_from": valid_from,
            "children": list(children)}


def _snapshot(root: Path) -> mirror.Snapshot:
    """A snapshot on disk in the layout mirror.py writes."""
    sohu = _node("BO_0", SOHU, "BO", "2026-08-24T10:00:00Z")
    pv1 = _node("DUB_0", PV1, "DUB", "2026-08-26T01:00:00Z", [sohu])
    module = _node("GPUM_3", MODULE, "GPUM", "2026-08-28T05:00:00Z", [pv1])
    serials = {
        UNIT: _payload(UNIT, [module],
                       process=[("2026-08-29T00:00:00Z", "Assy1", "ASSY", "PASS")],
                       kids_meta=[{"component_sn": MODULE, "component_name": "SOHU MOD",
                                   "slot_confidence": "location"}]),
        MODULE: _payload(MODULE, [pv1],
                         process=[("2026-08-27T07:43:10Z", "Sohu Module Test",
                                   "TEST", "PASS")],
                         kids_meta=[{"component_sn": PV1,
                                     "component_name": "PACER-PV1-NPI/IBC"}]),
        PV1: _payload(PV1, [sohu],
                      kids_meta=[{"component_sn": SOHU,
                                  "component_name": "INTERPOSER BOARD SOHU CHIP"}]),
        SOHU: _payload(SOHU),
    }
    for sn, body in serials.items():
        path = root / "sfis" / "serial" / f"{sn}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
    eos = {SOHU: [{"runId": "mlt_x_20260815", "level": "slt", "suite": "mlt",
                   "dutSerial": SOHU, "startedAt": "2026-08-15T21:46:03Z",
                   "version": "2026.220.0", "result": "fail"}]}
    (root / "eos").mkdir(parents=True, exist_ok=True)
    (root / "eos" / "by_dut.json").write_text(json.dumps(eos))
    snap = mirror.Snapshot(root)
    snap.manifest.update({
        "id": root.name,
        "taken_at": "2026-09-01T00:00:00Z",
        "sfis_payloads_through": "2026-08-31T23:00:00Z",
        "sources": {"sfis": {"ok": True}, "eos": {"ok": True, "verdicts_resolved": 1}},
        "sfis_scope": {"roots": [UNIT], "levels_swept": ["6U"]},
    })
    snap.save_manifest()
    return snap


class TraceJs(unittest.TestCase):
    def test_the_page_module_renders_the_tree_and_the_links(self):
        if not JSC.is_file():
            self.skipTest(f"JavaScriptCore not at {JSC} (macOS only)")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            snap = _snapshot(tmp / "snap")
            bundle = build_trace.build(snap, with_yaml=True)
            self.assertIn(UNIT, bundle["nodes"], "the unit is a root of the graph")
            self.assertIn(SOHU, bundle["nodes"], "the interposer is a node")
            out = build_trace.write(bundle, tmp / "trace.js")

            driver = tmp / "driver.js"
            driver.write_text(
                f"var ROOT = {json.dumps(str(ROOT))};\n"
                f"var BUNDLE = {json.dumps(str(out))};\n"
                f"load({json.dumps(str(ROOT / 'tests' / 'trace_dom_test.js'))});\n"
            )
            proc = subprocess.run(
                [str(JSC), str(driver)], capture_output=True, text=True, timeout=120
            )
            report = proc.stdout + proc.stderr
            self.assertNotIn("FAIL", report, "\n" + report)
            self.assertIn("trace.js: ok", report, "\n" + report)
            # Enough assertions to know the harness actually exercised it.
            self.assertGreaterEqual(report.count("ok   "), 12, "\n" + report)


if __name__ == "__main__":
    unittest.main()
