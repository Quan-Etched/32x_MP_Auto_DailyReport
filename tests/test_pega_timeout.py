"""A slow controller is not a dead one.

THE BUG THIS EXISTS FOR
The published weekly tracker sat frozen at 2026-W32 for three weeks while the
dashboard host collected happily every hour and reported success. Nothing was
broken in the sense anything logged: the box simply could not finish a pega
call inside eight seconds.

The controllers are in Hong Kong and the box is in us-west-2, with no direct
path between them — Tailscale relays through a DERP node. Measured from the box
on 2026-09-02, the *connect* alone took 5.1s, 7.3s and 12.5s on three hosts,
and one pega5 call took over 45s; the same calls from a laptop in the same city
as the controllers answer in under a second, which is where TIMEOUT = 8.0 came
from. At eight seconds the relayed path reads as a dead host.

That alone would have been a slow build. What made it three silent weeks is
that the first failure wrote the host off for the *whole build*: one slow
connect at the start of a tick and pega3, pega4 and pega5 were all served from
cache for every day of the run — a cache last warm on 08-09. The log said
"unreachable ... falling back to the cache" and the page said nothing at all.

So: a timeout takes several strikes, and any answer clears them. A host with
genuinely no route still gets written off, which is what the write-off is for.
"""

import socket
import unittest
import urllib.error

from factory import pega


class TimeoutIsNotDeath(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, pega, "_UNREACHABLE", pega._UNREACHABLE)
        self.addCleanup(setattr, pega, "_TIMEOUTS", pega._TIMEOUTS)
        self.addCleanup(setattr, pega, "TIMEOUT_STRIKES", pega.TIMEOUT_STRIKES)
        pega._UNREACHABLE = set()
        pega._TIMEOUTS = {}

    def test_a_timeout_is_told_apart_from_a_refusal(self):
        """urllib delivers it three different ways, and the reason chain is
        sometimes only a string."""
        for exc in (socket.timeout("timed out"),
                    TimeoutError("timed out"),
                    urllib.error.URLError(socket.timeout("timed out")),
                    urllib.error.URLError("<urlopen error timed out>")):
            with self.subTest(exc=repr(exc)):
                self.assertTrue(pega._is_timeout(exc))

        for exc in (ConnectionRefusedError("refused"),
                    urllib.error.URLError("[Errno 8] nodename nor servname "
                                          "provided"),
                    OSError("No route to host")):
            with self.subTest(exc=repr(exc)):
                self.assertFalse(pega._is_timeout(exc))

    def test_one_timeout_does_not_write_a_host_off(self):
        calls = []

        def slow(url, timeout=None):
            calls.append(url)
            raise urllib.error.URLError(socket.timeout("timed out"))

        self.addCleanup(setattr, pega.urllib.request, "urlopen",
                        pega.urllib.request.urlopen)
        pega.urllib.request.urlopen = slow

        with self.assertRaises(pega.PegaUnavailable):
            pega._get("/probe", host="pega4")
        self.assertNotIn("pega4", pega._UNREACHABLE,
                         "one slow connect is not evidence of a dead host")
        self.assertEqual(pega._TIMEOUTS["pega4"], 1)

        # It keeps trying, and keeps counting.
        with self.assertRaises(pega.PegaUnavailable):
            pega._get("/probe", host="pega4")
        self.assertNotIn("pega4", pega._UNREACHABLE)
        self.assertEqual(len(calls), 2, "the second call went to the network")

    def test_but_a_run_of_them_does(self):
        """Otherwise a box with no route pays the timeout once per day
        rebuilt, which is what the write-off exists to prevent."""
        def slow(url, timeout=None):
            raise urllib.error.URLError(socket.timeout("timed out"))

        self.addCleanup(setattr, pega.urllib.request, "urlopen",
                        pega.urllib.request.urlopen)
        pega.urllib.request.urlopen = slow

        for _ in range(pega.TIMEOUT_STRIKES):
            with self.assertRaises(pega.PegaUnavailable):
                pega._get("/probe", host="pega4")
        self.assertIn("pega4", pega._UNREACHABLE)

    def test_an_answer_clears_the_count(self):
        """A host that is merely slow must never accumulate its way to dead
        over a long build."""
        state = {"fail": True}

        class Response:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def flaky(url, timeout=None):
            if state["fail"]:
                raise urllib.error.URLError(socket.timeout("timed out"))
            return Response()

        self.addCleanup(setattr, pega.urllib.request, "urlopen",
                        pega.urllib.request.urlopen)
        pega.urllib.request.urlopen = flaky

        for _ in range(pega.TIMEOUT_STRIKES - 1):
            with self.assertRaises(pega.PegaUnavailable):
                pega._get("/probe", host="pega4")
        self.assertEqual(pega._TIMEOUTS["pega4"], pega.TIMEOUT_STRIKES - 1)

        state["fail"] = False
        self.assertEqual(pega._get("/probe", host="pega4"), {"ok": True})
        self.assertNotIn("pega4", pega._TIMEOUTS)

        # And having answered, it gets the full run of strikes again.
        state["fail"] = True
        for _ in range(pega.TIMEOUT_STRIKES - 1):
            with self.assertRaises(pega.PegaUnavailable):
                pega._get("/probe", host="pega4")
        self.assertNotIn("pega4", pega._UNREACHABLE)

    def test_a_host_that_cannot_be_reached_at_all_is_written_off_at_once(self):
        """A name that does not resolve will not fix itself between one day
        and the next, and paying that timeout per day is the original bug."""
        def refused(url, timeout=None):
            raise urllib.error.URLError("[Errno 8] nodename nor servname "
                                        "provided")

        self.addCleanup(setattr, pega.urllib.request, "urlopen",
                        pega.urllib.request.urlopen)
        pega.urllib.request.urlopen = refused

        with self.assertRaises(pega.PegaUnavailable):
            pega._get("/probe", host="pega4")
        self.assertIn("pega4", pega._UNREACHABLE)

    def test_the_timeout_clears_the_relayed_path_it_was_measured_against(self):
        """5.1s, 7.3s and 12.5s connects, one over 45s. Eight seconds cut all
        of them off; the point of the constant is to sit above them."""
        self.assertGreaterEqual(pega.TIMEOUT, 30)
        self.assertGreaterEqual(pega.TIMEOUT_STRIKES, 2)


if __name__ == "__main__":
    unittest.main()


class OfflineIsCacheOnly(unittest.TestCase):
    """FACTORY_PEGA_OFFLINE: the host has the data but cannot fetch it.

    Measured on the dashboard box 2026-09-03: one 50-run listing delivered
    8,452 of 26,400 bytes in 180 seconds — 46 B/s — over a DERP-relayed
    Tailscale path. The same call from a laptop takes 0.09s. Raising the
    timeout makes that path *work*; it does not make it usable, and a build
    that spends eight minutes rediscovering it is a build that will be turned
    off by whoever is waiting for it.
    """

    def setUp(self):
        import os
        import tempfile
        from pathlib import Path
        self.addCleanup(setattr, pega, "CACHE_DIR", pega.CACHE_DIR)
        self.addCleanup(setattr, pega, "_FELL_BACK", set(pega._FELL_BACK))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pega.CACHE_DIR = Path(tmp.name)
        pega._FELL_BACK = set()
        previous = os.environ.get("FACTORY_PEGA_OFFLINE")
        self.addCleanup(
            lambda: os.environ.__setitem__("FACTORY_PEGA_OFFLINE", previous)
            if previous is not None
            else os.environ.pop("FACTORY_PEGA_OFFLINE", None))
        os.environ["FACTORY_PEGA_OFFLINE"] = "1"

    PATH = "/api/history/data-analysis/suite-runs?start=2026-08-20"

    def test_it_serves_the_cache_without_touching_the_network(self):
        def explode(url, timeout=None):
            raise AssertionError("offline mode went to the network: " + url)

        self.addCleanup(setattr, pega.urllib.request, "urlopen",
                        pega.urllib.request.urlopen)
        pega.urllib.request.urlopen = explode

        pega._write_cache(self.PATH, {"total": 42}, host="pega4")
        self.assertEqual(
            pega._get(self.PATH, cache=True, host="pega4")["total"], 42)

    def test_and_says_the_answer_came_from_a_cached_copy(self):
        """The page reports its controller data as cached, exactly as it would
        after a failed fetch. Borrowed data, labelled as borrowed."""
        pega._write_cache(self.PATH, {"total": 42}, host="pega4")
        pega._get(self.PATH, cache=True, host="pega4")
        self.assertTrue(pega.fell_back("pega4"))

    def test_a_gap_in_the_cache_is_a_gap_and_not_a_silent_zero(self):
        with self.assertRaises(pega.PegaUnavailable):
            pega._get("/api/history/never-fetched", cache=True, host="pega4")

    def test_it_is_off_unless_asked_for(self):
        import os
        for setting in ("0", "", "false", "no"):
            os.environ["FACTORY_PEGA_OFFLINE"] = setting
            with self.subTest(setting=setting):
                self.assertFalse(pega.offline("pega3"))

    def test_it_names_hosts_because_the_fault_is_per_host(self):
        """The box reaches pega2 in 0.7s and pega6 in 2s; only pega3, pega4 and
        pega5 are relayed. Taking all five offline cost 696 unit runs — the two
        working hosts' entire contribution — which is why this is a list."""
        import os
        os.environ["FACTORY_PEGA_OFFLINE"] = "pega3,pega4,pega5"
        for host in ("pega3", "pega4", "pega5"):
            with self.subTest(host=host, expect="cache"):
                self.assertTrue(pega.offline(host))
        for host in ("pega2", "pega6"):
            with self.subTest(host=host, expect="network"):
                self.assertFalse(pega.offline(host))

    def test_a_bare_truth_value_still_means_every_host(self):
        """For a laptop off the VPN, where nothing is reachable."""
        import os
        for setting in ("1", "true", "yes"):
            os.environ["FACTORY_PEGA_OFFLINE"] = setting
            for host in ("pega2", "pega3", "pega6"):
                with self.subTest(setting=setting, host=host):
                    self.assertTrue(pega.offline(host))

    def test_the_list_is_forgiving_about_spacing_and_case(self):
        import os
        os.environ["FACTORY_PEGA_OFFLINE"] = " PEGA3 , pega4 "
        self.assertTrue(pega.offline("pega3"))
        self.assertTrue(pega.offline("Pega4"))
        self.assertFalse(pega.offline("pega5"))
