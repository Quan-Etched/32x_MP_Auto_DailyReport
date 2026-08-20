"""OCP against the controllers, run by run, for one day.

The whole risk in this module is one join. EOS records one run per *fixture*
with a single DUT serial; the controllers record one result per *unit*. Join
those on the serial and seven of every eight units come out "missing from OCP",
which is not a fault, it is the schema — and a report that says it anyway buries
the real gaps in noise.

So what is asserted here is the classification: that a unit absent because OCP
holds the fixture row instead is told apart from a unit absent because OCP has
nothing for that station at all, and that only the second reads as a fault.
"""

import unittest

from factory import reconcile


def unit(serial, station="mlt", version="mlt_2026.231.0-git91a99a1f",
         start=1_000_000, status="pass", suite=None, run="run_1"):
    return {"run": run, "id": run, "serial": serial, "station": station,
            "suite": suite if suite is not None else version,
            "version": version, "release": "231", "start": start,
            "status": status}


def bundle(rows, day="2026-08-20", **extra):
    runs = []
    for row in rows:
        runs.append({"i": row["id"], "d": row["serial"], "k": row["station"],
                     "su": row["suite"], "v": row["version"],
                     "r": row["release"], "day": day, "t": row["start"],
                     "s": row["status"]})
    return dict({"runs": runs}, **extra)


class ReleaseTest(unittest.TestCase):
    """The one token both sources spell the same, where they spell it at all."""

    def test_a_release_is_found_in_either_spelling(self):
        self.assertEqual(reconcile._release("2026.227.0-gite2b61375"),  # noqa: SLF001
                         "2026.227.0")
        self.assertEqual(
            reconcile._release("mlt_2026.231.0-git91a99a1f-tpm-permanent"),  # noqa: SLF001
            "2026.231.0")

    def test_a_suite_with_no_release_in_it_yields_nothing_not_a_guess(self):
        """pega4 reports the suite name as its version. Inventing a release from
        "L10_SFT" would make two unrelated runs corroborate each other."""
        self.assertEqual(reconcile._release("L10_SFT"), "")            # noqa: SLF001
        self.assertEqual(reconcile._release(""), "")                   # noqa: SLF001


class ClassifyTest(unittest.TestCase):
    """Why the other source does not have this unit — the only judgement here."""

    def test_no_runs_at_all_for_the_station_is_the_one_real_fault(self):
        """On 2026-08-20 OCP held nothing for MLT while the controllers held 79
        units. No schema difference explains that."""
        self.assertEqual(
            reconcile._classify(unit("A"), [unit("Z", station="htt")]),  # noqa: SLF001
            "station-absent")

    def test_the_fixture_row_standing_in_for_its_units_is_not_a_fault(self):
        """OCP has the same station and release inside the window — that is the
        one fixture row covering the eight units under it."""
        self.assertEqual(
            reconcile._classify(unit("A", start=1_000_000),             # noqa: SLF001
                                [unit("B", start=1_000_011)]),
            "fixture-not-unit")

    def test_a_run_too_far_away_in_time_does_not_excuse_the_gap(self):
        self.assertEqual(
            reconcile._classify(unit("A", start=1_000_000),             # noqa: SLF001
                                [unit("B", start=1_000_000 + 4 * 3600)]),
            "run-absent")

    def test_a_different_release_does_not_excuse_the_gap(self):
        self.assertEqual(
            reconcile._classify(unit("A", version="mlt_2026.231.0-gitaaa"),  # noqa: SLF001
                                [unit("B", version="mlt_2026.220.0-gitbbb")]),
            "run-absent")

    def test_without_a_release_on_either_side_the_gap_is_not_excused(self):
        """pega4's version field is a suite name, so there is no release to
        corroborate with. Absent evidence must not read as evidence."""
        self.assertEqual(
            reconcile._classify(unit("A", station="l10_sft", version="L10_SFT"),  # noqa: SLF001
                                [unit("B", station="l10_sft", version="L10_SFT")]),
            "run-absent")


class CompareDayTest(unittest.TestCase):
    def test_a_unit_both_sources_have_is_not_a_difference(self):
        rows = [unit("A")]
        out = reconcile.compare_day("2026-08-20", bundle(rows), bundle(rows))
        self.assertEqual(out["counts"]["missingFromOcp"], 0)
        self.assertEqual(out["counts"]["missingFromControllers"], 0)

    def test_both_directions_are_counted(self):
        """The controllers drop data too. A report that only looks one way calls
        those days clean."""
        out = reconcile.compare_day(
            "2026-08-20", bundle([unit("OCP_ONLY")]), bundle([unit("CTL_ONLY")]))
        self.assertEqual(out["counts"]["missingFromOcp"], 1)
        self.assertEqual(out["counts"]["missingFromControllers"], 1)

    def test_a_station_ocp_is_blind_to_is_flagged_on_its_row(self):
        out = reconcile.compare_day(
            "2026-08-20", bundle([unit("A", station="htt")]),
            bundle([unit("A", station="htt"), unit("B", station="mlt")]))
        blind = [row for row in out["stations"] if row["ocpBlind"]]
        self.assertEqual([row["station"] for row in blind], ["mlt"])

    def test_a_controller_slot_row_pairs_with_its_suite_run(self):
        """A controller row carries "#slot3" on its id; the suite run is the part
        in front, and that is what pairs with an OCP run."""
        rows = bundle([unit("A", run="mlt_x_run_abc")])
        rows["runs"][0]["i"] = "mlt_x_run_abc#slot3"
        out = reconcile.compare_day("2026-08-20", bundle([]), rows)
        self.assertEqual(out["missingFromOcp"][0]["run"], "mlt_x_run_abc")

    def test_another_day_is_not_compared(self):
        out = reconcile.compare_day(
            "2026-08-20", bundle([]), bundle([unit("A")], day="2026-08-19"))
        self.assertEqual(out["counts"]["missingFromOcp"], 0)

    def test_engineering_and_unclassified_are_left_out(self):
        """Neither is a station, and a debug build absent from OCP is not a
        finding about the line."""
        out = reconcile.compare_day(
            "2026-08-20", bundle([]),
            bundle([unit("A", station="engineering"),
                    unit("B", station="unclassified")]))
        self.assertEqual(out["counts"]["missingFromOcp"], 0)


class LatestDayTest(unittest.TestCase):
    def test_the_newest_day_either_source_has_wins(self):
        self.assertEqual(
            reconcile.latest_day(bundle([unit("A")], day="2026-08-19"),
                                 bundle([unit("B")], day="2026-08-20")),
            "2026-08-20")

    def test_no_days_at_all_yields_none(self):
        self.assertIsNone(reconcile.latest_day({"runs": []}))


class CsvTest(unittest.TestCase):
    def test_the_kind_is_a_column_so_a_reader_can_filter_the_noise_out(self):
        """The file is 133 rows on 08-20 and 50 of them are the schema, not a
        fault. Without the column somebody counts all 133."""
        self.assertIn("Kind", reconcile.CSV_HEADER)
        self.assertIn("DUT_SN", reconcile.CSV_HEADER)

    def test_a_csv_is_written_for_each_direction(self):
        import tempfile
        from pathlib import Path

        out = reconcile.compare_day(
            "2026-08-20", bundle([]), bundle([unit("A")]))
        with tempfile.TemporaryDirectory() as where:
            path = reconcile.write_csv(out, path=Path(where) / "x.csv")
            text = path.read_text(encoding="utf-8-sig")
        self.assertIn("DUT_SN", text.splitlines()[0])
        self.assertIn("A", text)
        self.assertIn("station-absent", text)


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
