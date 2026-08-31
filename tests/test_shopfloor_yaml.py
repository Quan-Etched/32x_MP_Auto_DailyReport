"""The one property the YAML writer exists for: a serial survives the round trip.

Every serial in this product is a digit string and several carry leading zeros —
``0905260051`` (manifold), ``0701260010`` (rack MFH). Emitted unquoted, a YAML
reader parses those as integers and ``0905260051`` comes back as ``905260051``:
a serial that matches nothing, silently, in the one file whose whole job is to
record which serial was where.

That is why ``shopfloor.yamlout`` exists instead of PyYAML's dumper, and this is
the test that keeps it honest.
"""

import unittest

from shopfloor import yamlout

#: Real shapes from live genealogy: leading-zero digits, plain digits,
#: alphanumeric vendor barcodes, and one with a dash.
SERIALS = [
    "0905260051", "0701260010", "268862070001", "28G5A00005",
    "JCS0R8001057", "705260033", "AH093025-57", "3546300006",
]


class YamlScalarQuoting(unittest.TestCase):
    def test_serials_round_trip_as_strings(self):
        data = {"parts": {"SLOT_%d" % i: {"sn": sn} for i, sn in enumerate(SERIALS)}}
        text = yamlout.dumps(data)
        try:
            import yaml
        except ImportError:  # pragma: no cover - stdlib-only environments
            self.skipTest("PyYAML not installed; cannot verify the round trip")
        back = yaml.safe_load(text)
        self.assertEqual([v["sn"] for v in back["parts"].values()], SERIALS)

    def test_leading_zero_serial_is_quoted(self):
        """The specific failure, called out on its own so a regression names itself."""
        self.assertIn("'0905260051'", yamlout.dumps({"sn": "0905260051"}))

    def test_empty_and_none_render_explicitly(self):
        """`[]` and `null` are answers. A key that silently vanished is not."""
        text = yamlout.dumps({"a": [], "b": {}, "c": None, "d": ""})
        for expected in ("a: []", "b: {}", "c: null", "d: ''"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
