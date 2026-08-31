"""The one property that matters: a serial written out reads back identical."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shopfloor import yamlout

LEADING_ZERO_SERIALS = ["0905260051", "0701260010", "268862070001", "28G5A00005",
                        "JCS0R8001057", "705260033", "AH093025-57", "3546300006"]


def test_serials_round_trip_as_strings():
    data = {"parts": {f"SLOT_{i}": {"sn": sn} for i, sn in enumerate(LEADING_ZERO_SERIALS)}}
    text = yamlout.dumps(data)
    for sn in LEADING_ZERO_SERIALS:
        assert f"'{sn}'" in text or f": {sn}\n" in text, sn
    try:
        import yaml  # optional; the assertion below is the real test
    except ImportError:
        return
    back = yaml.safe_load(text)
    got = [v["sn"] for v in back["parts"].values()]
    assert got == LEADING_ZERO_SERIALS, got


def test_empty_and_none():
    text = yamlout.dumps({"a": [], "b": {}, "c": None, "d": ""})
    assert "a: []" in text and "b: {}" in text and "c: null" in text and "d: ''" in text


if __name__ == "__main__":
    test_serials_round_trip_as_strings()
    test_empty_and_none()
    print("yamlout: ok")
