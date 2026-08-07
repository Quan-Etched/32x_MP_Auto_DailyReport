"""Release manifests and the compatibility diff.

The diff is the novel logic here, so it gets the most tests — especially the
confidence gating, which is what stops the page reporting 200 phantom removals
from a release that only had one run.
"""

import tempfile
import unittest
from pathlib import Path

from factory import items, releases


def sig(vtype="num", unit=None, instances=1, samples=10, chips=(), steps=(),
        prevalence=1.0, runs_present=3, stats=None, duts=2):
    return {
        "vtype": vtype, "unit": unit, "instances": instances, "samples": samples,
        "chips": list(chips), "steps": list(steps), "prevalence": prevalence,
        "runsPresent": runs_present, "duts": duts, "mixedType": False,
        "stats": stats,
    }


def stats(n=100, median=10.0, sd=1.0, p25=9.0, p75=11.0, lo=5.0, hi=15.0, p99=14.0):
    return {"n": n, "min": lo, "max": hi, "mean": median, "sd": sd,
            "p25": p25, "median": median, "p75": p75, "p99": p99}


CONFIDENT = {"release": "204", "station": "l10_sft", "runs": 10, "confident": True}
NEXT = {"release": "207", "station": "l10_sft", "runs": 12, "confident": True}
THIN = {"release": "203", "station": "l10_sft", "runs": 1, "confident": False}


class ClassificationTest(unittest.TestCase):
    def test_added_and_removed(self):
        d = releases.diff_signatures({"a": sig()}, {"b": sig()}, CONFIDENT, NEXT)
        self.assertEqual([e["item"] for e in d["added"]], ["b"])
        self.assertEqual([e["item"] for e in d["removed"]], ["a"])
        self.assertEqual(d["totals"], {"added": 1, "removed": 1, "changed": 0, "unchanged": 0})

    def test_identical_signature_is_unchanged(self):
        d = releases.diff_signatures({"a": sig()}, {"a": sig()}, CONFIDENT, NEXT)
        self.assertEqual(d["totals"]["unchanged"], 1)
        self.assertEqual(d["changed"], [])

    def test_unit_change_is_flagged(self):
        d = releases.diff_signatures({"a": sig(unit="Hz")}, {"a": sig(unit="MHz")},
                                     CONFIDENT, NEXT)
        self.assertIn(releases.KIND_UNIT, d["changed"][0]["kinds"])
        self.assertEqual(d["changed"][0]["notes"]["unit"], ["Hz", "MHz"])

    def test_type_change_is_flagged(self):
        d = releases.diff_signatures({"a": sig(vtype="num")}, {"a": sig(vtype="str")},
                                     CONFIDENT, NEXT)
        self.assertIn(releases.KIND_TYPE, d["changed"][0]["kinds"])

    def test_instance_and_chip_count_is_coverage_not_measurement(self):
        d = releases.diff_signatures({"a": sig(instances=10, chips=[0, 1])},
                                     {"a": sig(instances=9, chips=[0])},
                                     CONFIDENT, NEXT)
        entry = d["changed"][0]
        self.assertIn(releases.KIND_COVERAGE, entry["kinds"])
        self.assertEqual(entry["notes"]["instances"], [10, 9])
        self.assertEqual(entry["notes"]["chips"], [[0, 1], [0]])

    def test_step_reassignment_is_flagged(self):
        d = releases.diff_signatures({"a": sig(steps=["StepOne"])},
                                     {"a": sig(steps=["StepTwo"])}, CONFIDENT, NEXT)
        self.assertIn(releases.KIND_MOVED, d["changed"][0]["kinds"])

    def test_one_item_can_carry_several_kinds(self):
        d = releases.diff_signatures(
            {"a": sig(vtype="num", unit="Hz", instances=4)},
            {"a": sig(vtype="str", unit="MHz", instances=8)}, CONFIDENT, NEXT)
        kinds = d["changed"][0]["kinds"]
        for expected in (releases.KIND_TYPE, releases.KIND_UNIT, releases.KIND_COVERAGE):
            self.assertIn(expected, kinds)

    def test_changed_rows_sort_most_severe_first(self):
        before = {"shifty": sig(stats=stats()), "gone": sig(unit="Hz")}
        after = {"shifty": sig(stats=stats(median=40.0)), "gone": sig(vtype="str", unit="Hz")}
        d = releases.diff_signatures(before, after, CONFIDENT, NEXT)
        # type-changed outranks distribution-shift in SEVERITY.
        self.assertEqual(d["changed"][0]["item"], "gone")

    def test_counts_tally_every_kind(self):
        d = releases.diff_signatures(
            {"a": sig(unit="Hz"), "b": sig()}, {"a": sig(unit="V")}, CONFIDENT, NEXT)
        self.assertEqual(d["counts"][releases.KIND_UNIT], 1)
        self.assertEqual(d["counts"][releases.KIND_REMOVED], 1)


class ConfidenceTest(unittest.TestCase):
    """A thin release must never be allowed to assert a removal."""

    def test_thin_release_makes_the_whole_diff_low_confidence(self):
        d = releases.diff_signatures({"a": sig()}, {}, CONFIDENT, THIN)
        self.assertEqual(d["confidence"], "low")
        self.assertIn("cannot support add/remove", d["confidenceReason"])

    def test_every_add_remove_in_a_low_confidence_diff_is_weak(self):
        d = releases.diff_signatures({"a": sig()}, {"b": sig()}, CONFIDENT, THIN)
        self.assertTrue(d["removed"][0]["weak"])
        self.assertTrue(d["added"][0]["weak"])

    def test_confident_diff_is_not_weak(self):
        d = releases.diff_signatures({"a": sig()}, {"b": sig()}, CONFIDENT, NEXT)
        self.assertFalse(d["removed"][0]["weak"])

    def test_low_prevalence_is_weak_even_when_the_release_is_confident(self):
        # Present in 1 of 10 runs: its absence next release proves little.
        d = releases.diff_signatures({"a": sig(prevalence=0.1)}, {}, CONFIDENT, NEXT)
        self.assertTrue(d["removed"][0]["weak"])


class ShiftTest(unittest.TestCase):
    def test_sigma_move_beyond_the_threshold_is_a_shift(self):
        d = releases.diff_signatures(
            {"a": sig(stats=stats(median=10.0, sd=1.0))},
            {"a": sig(stats=stats(median=14.0, sd=1.0))}, CONFIDENT, NEXT)
        shift = d["changed"][0]["notes"]["shift"]
        self.assertTrue(shift["shifted"])
        self.assertAlmostEqual(shift["sigma"], 4.0)
        self.assertEqual(shift["direction"], "up")

    def test_small_move_is_not_a_shift(self):
        d = releases.diff_signatures(
            {"a": sig(stats=stats(median=10.0, sd=1.0))},
            {"a": sig(stats=stats(median=10.5, sd=1.0))}, CONFIDENT, NEXT)
        self.assertEqual(d["changed"], [])
        self.assertEqual(d["totals"]["unchanged"], 1)

    def test_fold_change_catches_what_sigma_cannot(self):
        # sd == 0 makes sigma unusable; a 2824 -> 0 collapse must still register.
        d = releases.diff_signatures(
            {"a": sig(stats=stats(median=2824.0, sd=0.0))},
            {"a": sig(stats=stats(median=0.0, sd=0.0))}, CONFIDENT, NEXT)
        shift = d["changed"][0]["notes"]["shift"]
        self.assertTrue(shift["shifted"])
        self.assertIsNone(shift["sigma"])

    def test_too_few_samples_reports_insufficient_rather_than_a_shift(self):
        d = releases.diff_signatures(
            {"a": sig(stats=stats(n=3, median=1.0))},
            {"a": sig(stats=stats(n=3, median=99.0))}, CONFIDENT, NEXT)
        self.assertEqual(d["changed"], [])

    def test_a_non_numeric_item_has_no_shift(self):
        d = releases.diff_signatures({"a": sig(vtype="str")}, {"a": sig(vtype="str")},
                                     CONFIDENT, NEXT)
        self.assertEqual(d["totals"]["unchanged"], 1)


class DetailNameTest(unittest.TestCase):
    def test_filename_is_filesystem_safe(self):
        self.assertEqual(releases.detail_name("l10_sft", "207"), "l10_sft-207.json")
        # A release string is API-derived, so it must not be able to escape.
        self.assertNotIn("/", releases.detail_name("l10_sft", "../../etc/passwd"))


class StoreBackedTest(unittest.TestCase):
    """release_meta and item_signatures against a real SQLite store."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.conn = items.open_db(Path(self.dir.name) / "items.sqlite")

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, run_id, release, item, values, unit=None, step="S", chip=None,
            vtype="num", dut="D1"):
        rows = [{
            "run_id": run_id, "dut": dut, "station": "l10_sft", "level": "l10",
            "suite": "L10_6U_SFT", "release": release, "start_ts": 1000,
            "step": step, "step_status": "COMPLETE", "item": item,
            "item_raw": "{}_{}".format(item, i), "chip": chip, "dims": None,
            "unit": unit, "vtype": vtype, "num": v if vtype == "num" else None,
            "txt": None if vtype == "num" else "t", "limits": None, "ts": None,
        } for i, v in enumerate(values)]
        # Append rather than replace, so several items can share one run.
        existing = [dict(r) for r in self.conn.execute(
            "SELECT * FROM items WHERE run_id = ?", (run_id,))]
        items.ingest(self.conn, run_id, existing + rows)

    def test_release_meta_marks_thin_releases(self):
        self.add("R1", "204", "x", [1, 2])
        self.add("R2", "204", "x", [1, 2])
        self.add("R3", "204", "x", [1, 2])
        self.add("R9", "207", "x", [1, 2])
        meta = {m["release"]: m for m in releases.release_meta(self.conn)}
        self.assertTrue(meta["204"]["confident"])     # 3 runs
        self.assertFalse(meta["207"]["confident"])    # 1 run
        self.assertEqual(meta["204"]["runs"], 3)

    def test_release_meta_sorts_releases_numerically(self):
        self.add("R1", "9", "x", [1])
        self.add("R2", "10", "x", [1])
        self.assertEqual([m["release"] for m in releases.release_meta(self.conn)],
                         ["9", "10"])

    def test_signatures_capture_unit_instances_and_prevalence(self):
        self.add("R1", "204", "temp", [40.0, 41.0], unit="degrees C")
        self.add("R2", "204", "temp", [42.0, 43.0], unit="degrees C")
        # Present in 1 of 3 runs -> prevalence 1/3.
        self.add("R3", "204", "other", [1.0])
        sigs = releases.item_signatures(self.conn, "l10_sft", "204")
        self.assertEqual(sigs["temp"]["unit"], "degrees C")
        self.assertEqual(sigs["temp"]["instances"], 2)
        self.assertAlmostEqual(sigs["temp"]["prevalence"], 2 / 3)
        self.assertAlmostEqual(sigs["other"]["prevalence"], 1 / 3)

    def test_numeric_stats_only_for_numeric_items(self):
        self.add("R1", "204", "num_item", [1.0, 2.0, 3.0])
        self.add("R1", "204", "str_item", [0], vtype="str")
        sigs = releases.item_signatures(self.conn, "l10_sft", "204")
        self.assertEqual(sigs["num_item"]["stats"]["median"], 2.0)
        self.assertIsNone(sigs["str_item"].get("stats"))

    def test_bundle_interns_names_and_splits_detail(self):
        self.add("R1", "204", "alpha", [1.0] * 40)
        self.add("R2", "204", "alpha", [1.0] * 40)
        self.add("R3", "204", "alpha", [1.0] * 40)
        self.add("R4", "207", "alpha", [9.0] * 40)
        self.add("R5", "207", "alpha", [9.0] * 40)
        self.add("R6", "207", "alpha", [9.0] * 40)
        bundle = releases.build_bundle(self.conn, {"runs": []})

        self.assertIn("alpha", bundle["items"])
        self.assertEqual(len(bundle["releases"]), 2)
        # Detail is keyed for separate files, not inlined in the index.
        self.assertIn("_detail", bundle)
        for entry in bundle["releases"]:
            self.assertNotIn("sig", entry)
            self.assertTrue(entry["detail"].endswith(".json"))
        # Numeric trends ride along in the index for the per-item graph.
        idx = str(bundle["items"].index("alpha"))
        self.assertEqual(len(bundle["trends"]["l10_sft"][idx]), 2)

    def test_write_bundle_emits_one_file_per_release(self):
        self.add("R1", "204", "alpha", [1.0])
        self.add("R2", "207", "alpha", [2.0])
        bundle = releases.build_bundle(self.conn, {"runs": []})
        out = Path(self.dir.name) / "releases.js"
        path, written = releases.write_bundle(bundle, out)
        self.assertEqual(written, 2)
        self.assertTrue(path.exists())
        self.assertEqual(len(list((out.parent / "releases").glob("*.json"))), 2)
        # The index must stay free of the bulky per-item detail.
        self.assertNotIn('"sig"', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
