"""The annotation service's refusals.

The page's sign-in is a gate on the interface. This is the gate on the data, so
what matters is what it turns away: a wrong password, a name that is not an
admin, a key that names no failure, and an attempt to write a field that is
derived rather than recorded.

That last one is the quiet risk. Root cause, corrective action and note are
people's work; error code, station, unit and FI link are derived from the
tracker and the catalogue. An editable copy of a derived value is a second
source of truth waiting to disagree with the first, so the service must ignore
those keys even when a request carries them.
"""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import annotate_server as service          # noqa: E402


EDIT = {"day": "2026-08-20", "station": "mlt", "dut": "A1",
        "case": "OneCodeTestCase"}
KEY = "2026-08-20|mlt|A1|OneCodeTestCase"


class ServiceTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "annotations.json"
        self._path, self._known = service.ANNOTATIONS, service.known_keys
        service.ANNOTATIONS = self.path
        service.known_keys = lambda: {KEY}

    def tearDown(self):
        service.ANNOTATIONS, service.known_keys = self._path, self._known
        self.tmp.cleanup()

    def stored(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())["entries"]

    def test_a_note_is_written_with_its_author_and_time(self):
        written, skipped = service.apply_edits(
            "eason", [dict(EDIT, note="seen on three boards")])
        self.assertEqual((1, []), (written, skipped))
        entry = self.stored()[KEY]
        self.assertEqual("seen on three boards", entry["note"])
        self.assertEqual("eason", entry["by"])
        self.assertTrue(entry["at"].startswith("20"), entry["at"])

    def test_only_the_three_recorded_fields_are_taken(self):
        """A request may carry anything. The derived ones are ignored."""
        service.apply_edits("chuck", [dict(
            EDIT, rootCause="a", correctiveAction="b", note="c",
            codes=["TH-FORGED-0001"], fi="http://evil/", message="rewritten",
            by="somebody-else", at="1999-01-01T00:00:00+00:00")])
        entry = self.stored()[KEY]
        self.assertEqual({"rootCause", "correctiveAction", "note", "by", "at"},
                         set(entry))
        self.assertEqual("chuck", entry["by"], "authorship is the service's")
        self.assertNotEqual("1999-01-01T00:00:00+00:00", entry["at"],
                            "so is the timestamp")

    def test_the_identity_fields_are_the_key_and_cannot_be_redirected(self):
        """day/station/dut/case are not editable *because* they address the
        row. Change one and you are asking about a different failure — which
        is refused unless that one is in the bundle too."""
        written, skipped = service.apply_edits(
            "chuck", [dict(EDIT, station="htt", note="filed against HTT")])
        self.assertEqual(0, written)
        self.assertIn("not in the error bundle", skipped[0])
        self.assertEqual({}, self.stored())

    def test_a_key_that_names_no_failure_is_refused(self):
        written, skipped = service.apply_edits(
            "chuck", [{"day": "1999-01-01", "station": "mlt", "dut": "0",
                       "case": "NopeTestCase", "note": "x"}])
        self.assertEqual(0, written)
        self.assertEqual(1, len(skipped))
        self.assertIn("not in the error bundle", skipped[0])
        self.assertEqual({}, self.stored())

    def test_an_edit_missing_its_identity_is_refused(self):
        written, skipped = service.apply_edits("chuck", [{"note": "x"}])
        self.assertEqual(0, written)
        self.assertIn("missing", skipped[0])

    def test_clearing_every_field_drops_the_entry(self):
        """Rather than leaving authorship attached to nothing."""
        service.apply_edits("chris", [dict(EDIT, note="temporary")])
        self.assertIn(KEY, self.stored())
        service.apply_edits("chris", [dict(EDIT, note="")])
        self.assertEqual({}, self.stored())

    def test_a_second_edit_merges_rather_than_replaces(self):
        service.apply_edits("chuck", [dict(EDIT, rootCause="the cause")])
        service.apply_edits("eason", [dict(EDIT, note="and a note")])
        entry = self.stored()[KEY]
        self.assertEqual("the cause", entry["rootCause"])
        self.assertEqual("and a note", entry["note"])
        self.assertEqual("eason", entry["by"], "the latest hand signs it")

    def test_an_over_long_field_is_refused(self):
        written, skipped = service.apply_edits(
            "chuck", [dict(EDIT, note="x" * (service.MAX_FIELD + 1))])
        self.assertEqual(0, written)
        self.assertIn("too long", skipped[0])


class CredentialTest(unittest.TestCase):
    """The names and the password are the service's, not the page's."""

    def test_the_admins_are_the_three_named(self):
        self.assertEqual(["chuck", "eason", "chris"], service.USERS)

    def test_the_password_is_not_empty(self):
        """A service accepting an empty password because the environment was
        not set would be worse than one that refuses to start."""
        self.assertTrue(service.PASSWORD)

    def test_only_three_fields_are_writable(self):
        self.assertEqual(("rootCause", "correctiveAction", "note"),
                         service.FIELDS)


if __name__ == "__main__":
    unittest.main()
