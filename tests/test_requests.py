"""The feature-request registry and its probes.

The probes reach the network, so they are stubbed here. What is worth pinning
is not whether a probe works — it is that the *page cannot overstate what a
probe knows*, which is where the first version of this went wrong twice.
"""

import unittest

from factory import requests as rq


class RegistryTest(unittest.TestCase):
    def test_every_entry_states_an_ask_and_a_done_condition(self):
        # An ask without a done-condition is a complaint.
        for entry in rq.REQUESTS:
            for field in ("key", "priority", "owner", "title", "need", "doneWhen"):
                self.assertTrue(entry.get(field), "%s missing %s" % (entry.get("key"), field))

    def test_keys_are_unique(self):
        keys = [entry["key"] for entry in rq.REQUESTS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_declared_probe_exists(self):
        for entry in rq.REQUESTS:
            if entry.get("check"):
                self.assertIn(entry["check"], rq.PROBES, entry["key"])


class BundleTest(unittest.TestCase):
    def build(self, **kwargs):
        return rq.build_bundle({}, **kwargs)

    def test_unprobed_entries_are_open_not_unknown(self):
        # "open" means nobody automated a check; "unknown" means a check ran and
        # could not answer. Collapsing them hides which needs a person.
        bundle = self.build(probe=False)
        by_key = {e["key"]: e for e in bundle["requests"]}
        self.assertEqual(by_key["per-unit-verdict"]["status"]["state"], rq.OPEN)

    def test_decisions_are_marked_as_decisions(self):
        by_key = {e["key"]: e for e in self.build(probe=False)["requests"]}
        self.assertEqual(by_key["site-auth"]["status"]["state"], rq.DECISION)
        self.assertEqual(by_key["htt-version"]["status"]["state"], rq.DECISION)

    def test_no_probe_means_no_checked_timestamp(self):
        # A status with a timestamp implies something was verified then. An
        # un-probed entry must not carry one.
        for entry in self.build(probe=False)["requests"]:
            self.assertNotIn("checkedAt", entry["status"], entry["key"])

    def test_a_probe_records_when_it_ran(self):
        rq.PROBES["jira"] = lambda payload: {"state": rq.RESOLVED, "note": "stub"}
        self.addCleanup(lambda: rq.PROBES.__setitem__("jira", rq._probe_jira))
        by_key = {e["key"]: e for e in self.build()["requests"]}
        self.assertIn("checkedAt", by_key["jira-base"]["status"])

    def test_a_throwing_probe_does_not_take_the_build_with_it(self):
        def boom(payload):
            raise RuntimeError("no route")
        rq.PROBES["jira"] = boom
        self.addCleanup(lambda: rq.PROBES.__setitem__("jira", rq._probe_jira))
        by_key = {e["key"]: e for e in self.build()["requests"]}
        self.assertEqual(by_key["jira-base"]["status"]["state"], rq.UNKNOWN)
        self.assertIn("no route", by_key["jira-base"]["status"]["note"])

    def test_blocking_count_covers_open_as_well_as_blocked(self):
        # An ask nobody checks is not thereby unblocked.
        bundle = self.build(probe=False)
        expected = sum(1 for e in bundle["requests"]
                       if e["priority"] in ("P0", "P1"))
        self.assertEqual(bundle["openBlocking"], expected)

    def test_the_bundle_names_the_host_that_answered(self):
        # A probe is only true where it ran, so the page has to be able to say
        # where that was.
        self.assertTrue(self.build(probe=False)["builtOn"])

    def test_bundle_is_json_serialisable(self):
        import json
        json.dumps(self.build(probe=False))


class ProbeTest(unittest.TestCase):
    def test_l11_reads_the_last_collect_rather_than_asserting(self):
        blocked = rq._probe_l11({"levelErrors": {"l11": "... s3:ListBucket ..."}})
        self.assertEqual(blocked["state"], rq.BLOCKED)
        self.assertIn("ListBucket", blocked["note"])

        ok = rq._probe_l11({"runs": [{"level": "l11"}]})
        self.assertEqual(ok["state"], rq.RESOLVED)

        quiet = rq._probe_l11({"runs": [{"level": "module"}]})
        self.assertEqual(quiet["state"], rq.UNKNOWN)

    def test_slot_serial_resolves_only_on_a_real_slot_field(self):
        self.assertEqual(rq._probe_slot_serial({"runs": [{"dutSerial": "1"}]})["state"],
                         rq.BLOCKED)
        self.assertEqual(rq._probe_slot_serial(
            {"runs": [{"dutSerial": "1", "participating": [{"dut_sn": "2"}]}]})["state"],
            rq.RESOLVED)

    def test_pega_probe_names_its_vantage(self):
        # "reachable from here" is not "reachable from the dashboard host", and
        # the ask is about the dashboard host.
        from factory import pega
        self.addCleanup(setattr, pega, "available", pega.available)
        pega.available = lambda: True
        status = rq._probe_pega({})
        self.assertEqual(status["state"], rq.RESOLVED)
        self.assertIn(rq._hostname(), status["note"])
        self.assertEqual(status["vantage"], rq._hostname())


if __name__ == "__main__":
    unittest.main()
