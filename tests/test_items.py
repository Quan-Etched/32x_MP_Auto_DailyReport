"""Test-item flattening: templating, dimensions, extraction, storage."""

import json
import tempfile
import unittest
from pathlib import Path

from factory import items


class TemplateTest(unittest.TestCase):
    """Templating is what turns thousands of one-sample names into items."""

    def test_index_runs_collapse(self):
        self.assertEqual(items.template_name("ber_0_0_1"), "ber_<i>_<i>_<i>")
        self.assertEqual(items.template_name("ber_2_7_127"), "ber_<i>_<i>_<i>")
        # Same physical measurement on different lanes must be ONE item.
        self.assertEqual(items.template_name("ber_0_0_1"), items.template_name("ber_0_0_2"))

    def test_chip_prefix_collapses_too(self):
        self.assertEqual(items.template_name("chip0_pd_north_east_chain_12"),
                         items.template_name("chip3_pd_north_east_chain_7"))

    def test_names_without_indices_are_untouched(self):
        self.assertEqual(items.template_name("BIOS Fixed Boot Order"), "BIOS Fixed Boot Order")
        self.assertEqual(items.template_name("OS Version"), "OS Version")

    def test_embedded_version_like_tokens_are_not_mangled_away(self):
        # A trailing index becomes <i>, but the item stays recognisable.
        self.assertTrue(items.template_name("llama70b_forward").startswith("llama"))

    def test_blank_names(self):
        self.assertEqual(items.template_name(None), "(unnamed)")
        self.assertEqual(items.template_name("  "), "(unnamed)")


class ChipTest(unittest.TestCase):
    def test_name_prefix_wins(self):
        self.assertEqual(items.derive_chip("chip5_sensor_3", None), 5)
        self.assertEqual(items.derive_chip("chip_2_status", None), 2)

    def test_falls_back_to_metadata_device_index(self):
        self.assertEqual(items.derive_chip("ber_0_0_1", {"device_index": 3}), 3)

    def test_none_when_unattributable(self):
        self.assertIsNone(items.derive_chip("OS Version", None))
        self.assertIsNone(items.derive_chip("ber_0_0_1", {"phy_idx": 0}))


class ValueTest(unittest.TestCase):
    def test_numeric_kinds(self):
        self.assertEqual(items.classify_value(3)[0], items.NUM)
        self.assertEqual(items.classify_value(2.5e-10)[0], items.NUM)

    def test_bool_is_kept_distinct_from_a_measurement(self):
        # Stored numerically so a pass-rate is an average, but never plotted as
        # a distribution.
        kind, num, _ = items.classify_value(True)
        self.assertEqual((kind, num), (items.BOOL, 1.0))
        self.assertEqual(items.classify_value(False)[1], 0.0)

    def test_strings_go_to_text(self):
        kind, num, txt = items.classify_value("ubuntu 24.04")
        self.assertEqual((kind, num, txt), (items.STR, None, "ubuntu 24.04"))

    def test_nan_and_inf_never_reach_an_aggregate(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            self.assertEqual(items.classify_value(bad)[0], items.STR)


class ExtractTest(unittest.TestCase):
    # NB: not named `run` -- that would shadow TestCase.run().
    meta = {"runId": "R1", "dutSerial": "D1", "stationKey": "l10_sft", "level": "l10",
           "suite": "L10_6U_SFT", "version": "2026.207.0-gitabc", "startTs": 1785826988}

    stream = "\n".join([
        '{"testStepArtifact":{"testStepId":"7","testStepStart":{"name":"C2cIntegrityTestCase"}},'
        '"timestamp":"2026-08-04T07:03:10Z"}',
        '{"testStepArtifact":{"testStepId":"7","measurement":{"name":"ber_0_0_1",'
        '"value":2.5e-10,"validators":[],'
        '"metadata":{"device_index":0,"phy_idx":0,"lane_idx":1}}},'
        '"timestamp":"2026-08-04T07:03:11Z"}',
        '{"testStepArtifact":{"testStepId":"7","measurement":{"name":"chip3_sensor_2",'
        '"value":45,"unit":"degrees C","validators":[]}},"timestamp":"2026-08-04T07:03:12Z"}',
        '{"testStepArtifact":{"testStepId":"7","testStepEnd":{"status":"COMPLETE"}},'
        '"timestamp":"2026-08-04T07:03:13Z"}',
    ])

    def rows(self):
        return items.extract_items(self.stream, self.meta)

    def test_one_row_per_measurement(self):
        self.assertEqual(len(self.rows()), 2)

    def test_run_context_is_denormalized_onto_every_row(self):
        row = self.rows()[0]
        self.assertEqual(row["dut"], "D1")
        self.assertEqual(row["station"], "l10_sft")
        self.assertEqual(row["release"], "207")   # from 2026.207.0

    def test_step_name_and_status_are_attached_even_though_end_comes_later(self):
        # The step's verdict is only known after the measurements were emitted;
        # every row must still carry it, or the bridge back to the boolean
        # test case is lost.
        for row in self.rows():
            self.assertEqual(row["step"], "C2cIntegrityTestCase")
            self.assertEqual(row["step_status"], "COMPLETE")

    def test_dimensions_and_units_survive(self):
        ber, sensor = self.rows()
        self.assertEqual(json.loads(ber["dims"])["lane_idx"], 1)
        self.assertEqual(ber["item"], "ber_<i>_<i>_<i>")
        self.assertEqual(sensor["unit"], "degrees C")
        self.assertEqual(sensor["chip"], 3)

    def test_empty_validators_are_recorded_as_no_published_limit(self):
        # The whole point: today this is always None. It must become non-None
        # by itself the day the harness starts populating validators.
        self.assertIsNone(self.rows()[0]["limits"])

    def test_populated_validators_are_captured(self):
        stream = ('{"testStepArtifact":{"testStepId":"1","measurement":{"name":"t","value":9,'
                  '"validators":[{"type":"LESS_THAN","value":10}]}}}')
        row = items.extract_items(stream, self.meta)[0]
        self.assertEqual(json.loads(row["limits"])[0]["type"], "LESS_THAN")

    def test_truncated_and_junk_streams(self):
        self.assertEqual(items.extract_items("not json", self.meta), [])
        self.assertEqual(items.extract_items(b"", self.meta), [])
        truncated = self.stream.rsplit("\n", 1)[0] + '\n{"testStepArtifact":{"meas'
        self.assertEqual(len(items.extract_items(truncated, self.meta)), 2)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.conn = items.open_db(Path(self.dir.name) / "items.sqlite")

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def rows_for(self, run_id, dut, values, status="COMPLETE"):
        return [{
            "run_id": run_id, "dut": dut, "station": "l10_sft", "level": "l10",
            "suite": "S", "release": "207", "start_ts": 1, "step": "T",
            "step_status": status, "item": "ber_<i>", "item_raw": "ber_%d" % i,
            "chip": None, "dims": None, "unit": None, "vtype": "num",
            "num": v, "txt": None, "limits": None, "ts": None,
        } for i, v in enumerate(values)]

    def test_ingest_is_idempotent(self):
        self.assertEqual(items.ingest(self.conn, "R1", self.rows_for("R1", "D1", [1, 2, 3])), 3)
        items.ingest(self.conn, "R1", self.rows_for("R1", "D1", [1, 2, 3]))
        # Re-collecting a run must not double-count it.
        self.assertEqual(items.summary_counts(self.conn)["rows"], 3)
        self.assertTrue(items.already_ingested(self.conn, "R1"))

    def test_stats_over_the_population(self):
        items.ingest(self.conn, "R1", self.rows_for("R1", "D1", [1, 2, 3, 4, 5]))
        stats = items.item_stats(self.conn, "ber_<i>", "l10_sft")
        self.assertEqual(stats["samples"], 5)
        self.assertEqual(stats["median"], 3)
        self.assertEqual(stats["min"], 1)
        self.assertEqual(stats["max"], 5)

    def test_population_can_be_restricted_to_build_an_empirical_limit(self):
        items.ingest(self.conn, "R1", self.rows_for("R1", "D1", [1, 1, 1], "COMPLETE"))
        items.ingest(self.conn, "R2", self.rows_for("R2", "D2", [90, 95], "ERROR"))
        passing = items.item_stats(self.conn, "ber_<i>", "l10_sft", only_status="COMPLETE")
        self.assertEqual(passing["samples"], 3)
        self.assertEqual(passing["max"], 1)

    def test_per_dut_reduces_within_the_unit_first(self):
        # 3 lanes on D1, 2 on D2 -> one row per unit, not per lane.
        items.ingest(self.conn, "R1", self.rows_for("R1", "D1", [1, 9, 3]))
        items.ingest(self.conn, "R2", self.rows_for("R2", "D2", [4, 5]))
        rows = items.per_dut(self.conn, "ber_<i>", "l10_sft", agg="MAX")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["value"], 9)
        self.assertEqual(rows[0]["lanes"], 3)

    def test_rejects_an_unsupported_aggregate(self):
        with self.assertRaises(ValueError):
            items.per_dut(self.conn, "x", agg="DROP TABLE items")

    def test_catalog_needs_more_than_one_dut_to_be_a_distribution(self):
        items.ingest(self.conn, "R1", self.rows_for("R1", "D1", [1, 2]))
        self.assertEqual(items.catalog(self.conn), [])
        items.ingest(self.conn, "R2", self.rows_for("R2", "D2", [3]))
        self.assertEqual(items.catalog(self.conn)[0]["duts"], 2)


class MarginTest(unittest.TestCase):
    def test_sigma_from_the_reference_population(self):
        stats = {"mean": 10.0, "sd": 2.0}
        self.assertEqual(items.margin(16.0, stats), 3.0)
        self.assertEqual(items.margin(10.0, stats), 0.0)

    def test_no_spread_means_no_margin_rather_than_a_divide_by_zero(self):
        self.assertIsNone(items.margin(5.0, {"mean": 5.0, "sd": 0.0}))
        self.assertIsNone(items.margin(5.0, {}))


class HistogramTest(unittest.TestCase):
    def test_bins_span_the_range(self):
        h = items.histogram([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], bins=5)
        self.assertEqual(sum(h["bins"]), 10)
        self.assertEqual((h["lo"], h["hi"]), (0, 9))

    def test_degenerate_inputs(self):
        self.assertEqual(items.histogram([])["bins"], [])
        self.assertEqual(items.histogram([4, 4, 4])["bins"], [3])


if __name__ == "__main__":
    unittest.main()
