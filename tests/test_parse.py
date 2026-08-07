"""Parsing is the layer most exposed to an unverified API schema, so it gets the
most tests: every alias spelling, every status word, every timestamp shape.
"""

import unittest
from datetime import datetime, timezone

from factory import parse


class NormalizeStatusTest(unittest.TestCase):
    def test_common_spellings(self):
        for value in ("pass", "PASSED", "ok", "Success", True, 1, "P"):
            self.assertEqual(parse.normalize_status(value), "pass", value)
        for value in ("fail", "FAILED", "nok", False, 0):
            self.assertEqual(parse.normalize_status(value), "fail", value)
        for value in ("error", "TIMEOUT", "aborted", "crash"):
            self.assertEqual(parse.normalize_status(value), "error", value)
        for value in ("skipped", "N/A", "blocked"):
            self.assertEqual(parse.normalize_status(value), "skip", value)

    def test_decorated_values_fall_back_to_substring(self):
        self.assertEqual(parse.normalize_status("FAILED (assertion at line 12)"), "fail")
        self.assertEqual(parse.normalize_status("PASS_WITH_WARNINGS"), "pass")

    def test_unknown_and_empty(self):
        self.assertEqual(parse.normalize_status(None), "unknown")
        self.assertEqual(parse.normalize_status(""), "unknown")
        self.assertEqual(parse.normalize_status("banana"), "unknown")

    def test_skip_does_not_count_against_yield(self):
        self.assertTrue(parse.is_failure("fail"))
        self.assertTrue(parse.is_failure("error"))
        self.assertFalse(parse.is_failure("skip"))
        self.assertFalse(parse.is_failure("pass"))


class EosStatusVocabularyTest(unittest.TestCase):
    """The exact status words observed in live EOS test_summary.json payloads.

    Verified against l10/slt/module runs: PASSED, FAILED, ERROR, TIMEOUT,
    SKIPPED, INTERRUPTED, EXITED. Getting INTERRUPTED wrong matters most — it is
    the majority of entries on any aborted run.
    """

    def test_live_vocabulary_is_fully_mapped(self):
        expected = {
            "PASSED": "pass",
            "FAILED": "fail",
            "ERROR": "error",
            "TIMEOUT": "error",
            "SKIPPED": "skip",
            "INTERRUPTED": "skip",
            "EXITED": "error",
        }
        for raw, want in expected.items():
            self.assertEqual(parse.normalize_status(raw), want, raw)

    def test_interrupted_is_not_a_failure(self):
        # A suite that aborts leaves dozens of INTERRUPTED entries. Counting
        # them as failures would tank yield on every aborted run.
        self.assertFalse(parse.is_failure(parse.normalize_status("INTERRUPTED")))


class EventStreamTest(unittest.TestCase):
    """The event stream is the ONLY source of run duration and verdict."""

    stream = "\n".join([
        '{"schemaVersion":{"major":2},"sequenceNumber":0,"timestamp":"2026-08-04T07:03:08Z"}',
        '{"testRunArtifact":{"testRunStart":{"name":"L10_tests"}},"timestamp":"2026-08-04T07:03:08Z"}',
        '{"testStepArtifact":{"testStepId":"0","testStepStart":{"name":"CheckBiosBootOrder"}},'
        '"timestamp":"2026-08-04T07:03:10Z"}',
        '{"testStepArtifact":{"testStepId":"0","testStepEnd":{"status":"COMPLETE"}},'
        '"timestamp":"2026-08-04T07:03:40Z"}',
        '{"testRunArtifact":{"testRunEnd":{"status":"ERROR","result":"NOT_APPLICABLE"}},'
        '"timestamp":"2026-08-04T07:43:26Z"}',
    ])

    def test_extracts_run_window_duration_and_verdict(self):
        result = parse.parse_event_stream(self.stream)
        self.assertEqual(result["startTs"], parse.parse_timestamp("2026-08-04T07:03:08Z"))
        self.assertEqual(result["endTs"], parse.parse_timestamp("2026-08-04T07:43:26Z"))
        self.assertEqual(result["durationSec"], 2418.0)
        self.assertEqual(result["status"], "error")

    def test_per_step_durations_are_keyed_by_display_name(self):
        self.assertEqual(
            parse.parse_event_stream(self.stream)["stepDurations"],
            {"CheckBiosBootOrder": 30.0},
        )

    def test_ocp_outcome_folding(self):
        def verdict(status, result):
            stream = ('{"testRunArtifact":{"testRunEnd":{"status":"%s","result":"%s"}},'
                      '"timestamp":"2026-08-04T07:00:00Z"}' % (status, result))
            return parse.parse_event_stream(stream)["status"]

        self.assertEqual(verdict("COMPLETE", "PASS"), "pass")
        self.assertEqual(verdict("COMPLETE", "FAIL"), "fail")
        self.assertEqual(verdict("ERROR", "NOT_APPLICABLE"), "error")
        self.assertEqual(verdict("COMPLETE", "NOT_APPLICABLE"), "unknown")

    def test_truncated_stream_parses_as_far_as_it_can(self):
        # A run that died mid-write leaves a half-written final line.
        truncated = self.stream.rsplit("\n", 1)[0] + '\n{"testRunArtifact":{"testRun'
        result = parse.parse_event_stream(truncated)
        self.assertIsNotNone(result["startTs"])
        self.assertIsNone(result["status"])

    def test_empty_and_junk_input(self):
        for value in ("", b"", None, "not json at all"):
            result = parse.parse_event_stream(value)
            self.assertIsNone(result["durationSec"], value)


class SuiteSummaryDisplayNameTest(unittest.TestCase):
    def test_unique_id_is_the_grouping_key_display_name_is_kept(self):
        # EOS ships both; the stable ID groups the Pareto, the display name
        # joins to the event stream's step names.
        raw = ('[{"test_name":"CheckBiosBootOrder","unique_id":"CHK_BIOS_BOOT_ORDER",'
               '"status":"FAILED","log_file":"a.log","parent_id":null}]')
        test = parse.parse_suite_summary(raw)[0]
        self.assertEqual(test["name"], "CHK_BIOS_BOOT_ORDER")
        self.assertEqual(test["displayName"], "CheckBiosBootOrder")


class PickTest(unittest.TestCase):
    def test_matches_regardless_of_punctuation_and_case(self):
        for key in ("dutSerial", "dut_serial", "DUT-Serial", "dutserial"):
            self.assertEqual(parse.pick({key: "267"}, parse.DUT_ALIASES), "267")

    def test_prefers_earlier_alias_and_skips_blanks(self):
        self.assertEqual(parse.pick({"dut": "", "serial": "9"}, parse.DUT_ALIASES), "9")

    def test_missing_returns_default(self):
        self.assertIsNone(parse.pick({"other": 1}, parse.DUT_ALIASES))
        self.assertEqual(parse.pick("not-a-dict", parse.DUT_ALIASES, "x"), "x")


class TimestampTest(unittest.TestCase):
    def test_iso_variants_agree(self):
        expected = int(datetime(2026, 8, 3, 8, tzinfo=timezone.utc).timestamp())
        self.assertEqual(parse.parse_timestamp("2026-08-03T08:00:00Z"), expected)
        self.assertEqual(parse.parse_timestamp("2026-08-03T08:00:00+00:00"), expected)
        self.assertEqual(parse.parse_timestamp("2026-08-03T08:00:00"), expected)

    def test_offsets_are_respected(self):
        self.assertEqual(
            parse.parse_timestamp("2026-08-03T01:00:00-07:00"),
            parse.parse_timestamp("2026-08-03T08:00:00Z"),
        )

    def test_epoch_seconds_and_millis(self):
        self.assertEqual(parse.parse_timestamp(1754208000), 1754208000)
        self.assertEqual(parse.parse_timestamp(1754208000000), 1754208000)
        self.assertEqual(parse.parse_timestamp("1754208000"), 1754208000)

    def test_rubbish_is_none_not_an_exception(self):
        for value in (None, "", "not a date", True):
            self.assertIsNone(parse.parse_timestamp(value), value)

    def test_recovers_time_from_run_id_suffix(self):
        run_id = "L10_tests_2026.214.0-gita7f2fadc_20260803_094406"
        self.assertEqual(
            parse.timestamp_from_run_id(run_id),
            parse.parse_timestamp("2026-08-03T09:44:06Z"),
        )
        self.assertIsNone(parse.timestamp_from_run_id("no-stamp-here"))


class DurationTest(unittest.TestCase):
    def test_numbers_clock_and_units(self):
        self.assertEqual(parse.parse_duration(90), 90.0)
        self.assertEqual(parse.parse_duration("90.5"), 90.5)
        self.assertEqual(parse.parse_duration("00:01:30"), 90.0)
        self.assertEqual(parse.parse_duration("1m30s"), 90.0)
        self.assertEqual(parse.parse_duration("2h"), 7200.0)

    def test_unparseable_is_none(self):
        self.assertIsNone(parse.parse_duration("a while"))
        self.assertIsNone(parse.parse_duration(None))


class SuiteSummaryTest(unittest.TestCase):
    """The doc does not pin this schema, so all three plausible shapes parse."""

    expected = [
        {"name": "CHK_BIOS_BOOT_ORDER", "status": "pass"},
        {"name": "CHK_PCIE_LINK_WIDTH", "status": "fail"},
    ]

    def _names_and_statuses(self, parsed):
        return [{"name": t["name"], "status": t["status"]} for t in parsed]

    def test_bare_list(self):
        raw = """[
          {"name": "CHK_BIOS_BOOT_ORDER", "status": "PASS"},
          {"name": "CHK_PCIE_LINK_WIDTH", "status": "FAIL"}
        ]"""
        self.assertEqual(self._names_and_statuses(parse.parse_suite_summary(raw)), self.expected)

    def test_wrapped_list(self):
        raw = """{"suite": "L10_tests", "tests": [
          {"testName": "CHK_BIOS_BOOT_ORDER", "result": "passed"},
          {"testName": "CHK_PCIE_LINK_WIDTH", "result": "failed"}
        ]}"""
        self.assertEqual(self._names_and_statuses(parse.parse_suite_summary(raw)), self.expected)

    def test_mapping_of_name_to_entry(self):
        raw = """{
          "CHK_BIOS_BOOT_ORDER": {"status": "ok"},
          "CHK_PCIE_LINK_WIDTH": {"status": "nok"}
        }"""
        parsed = sorted(parse.parse_suite_summary(raw), key=lambda t: t["name"])
        self.assertEqual(self._names_and_statuses(parsed), self.expected)

    def test_log_file_is_carried_through_for_drill_down(self):
        raw = """[{"name": "T", "status": "fail",
                   "log_file": "artifacts/T/iteration_1/t.log", "duration": 12}]"""
        test = parse.parse_suite_summary(raw)[0]
        self.assertEqual(test["logFile"], "artifacts/T/iteration_1/t.log")
        self.assertEqual(test["durationSec"], 12.0)

    def test_bytes_and_broken_json(self):
        self.assertEqual(parse.parse_suite_summary(b'[{"name":"T","status":"pass"}]')[0]["name"], "T")
        self.assertEqual(parse.parse_suite_summary(b"not json"), [])
        self.assertEqual(parse.parse_suite_summary(None), [])


class ParseRunTest(unittest.TestCase):
    def test_full_run_object(self):
        record = parse.parse_run(
            {
                "runId": "L10_tests_v1_20260803_094406",
                "dutSerial": "267694410001",
                "station": "ST-02",
                "suite": "L10_tests",
                "version": "2026.214.0",
                "startTime": "2026-08-03T16:44:06Z",
                "endTime": "2026-08-03T16:54:06Z",
                "status": "PASS",
            },
            "l10",
        )
        self.assertEqual(record["dutSerial"], "267694410001")
        self.assertEqual(record["station"], "ST-02")
        self.assertEqual(record["status"], "pass")
        self.assertEqual(record["durationSec"], 600.0)
        self.assertFalse(record["startFromRunId"])

    def test_falls_back_to_the_run_id_timestamp_and_flags_it(self):
        record = parse.parse_run(
            {"runId": "L10_tests_v1_20260803_094406", "dut": "1"}, "l10"
        )
        self.assertTrue(record["startFromRunId"])
        self.assertEqual(record["startTs"], parse.parse_timestamp("2026-08-03T09:44:06Z"))

    def test_status_is_derived_from_tests_when_absent(self):
        record = parse.parse_run({"runId": "r1", "dutSerial": "1"}, "l10")
        record["tests"] = parse.parse_suite_summary(
            '[{"name":"A","status":"pass"},{"name":"B","status":"fail"}]'
        )
        parse.summarize_tests(record)
        self.assertEqual(record["status"], "fail")
        self.assertEqual(record["testCounts"]["fail"], 1)
        self.assertEqual([f["test"] for f in record["failures"]], ["B"])

    def test_an_api_status_is_not_overridden_by_the_tests(self):
        record = parse.parse_run({"runId": "r1", "dutSerial": "1", "status": "pass"}, "l10")
        record["tests"] = parse.parse_suite_summary('[{"name":"A","status":"fail"}]')
        parse.summarize_tests(record)
        self.assertEqual(record["status"], "pass")


if __name__ == "__main__":
    unittest.main()
