"""What a scheduler tick does when EOS does not answer.

Written after a run pointed at a dead host reduced a 30-day snapshot to 0 runs
and the station bundle from 145 KB to 18 KB, without raising anything: the
collector records the failure per level and returns an empty payload, which was
then written over the collected history and published as a dashboard reading
zero everywhere.
"""

import unittest

from factory import cli


class EmptyFetchTest(unittest.TestCase):
    def test_no_runs_and_a_level_error_is_a_failure(self):
        self.assertTrue(cli._is_empty_failure(
            {"runs": [], "levelErrors": {"module": "connection refused"}}))

    def test_a_genuinely_quiet_window_is_not_a_failure(self):
        """A shift where the line tested nothing is data, not an outage, and
        must still be written or the page never goes quiet when the line does."""
        self.assertFalse(cli._is_empty_failure({"runs": [], "levelErrors": {}}))

    def test_runs_plus_one_dead_level_is_not_a_failure(self):
        """One level down out of five is normal; the other four are real data
        and the page names the level that failed."""
        self.assertFalse(cli._is_empty_failure(
            {"runs": [{"runId": "a"}], "levelErrors": {"l11": "timeout"}}))

    def test_a_payload_with_neither_is_not_a_failure(self):
        self.assertFalse(cli._is_empty_failure({}))


if __name__ == "__main__":
    unittest.main()
