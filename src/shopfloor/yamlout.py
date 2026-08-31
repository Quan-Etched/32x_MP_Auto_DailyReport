"""A small deterministic YAML writer, stdlib only.

WHY NOT PyYAML
--------------
Two reasons, and the second is the real one.

1. This repo is stdlib-only so it runs unattended on a factory host with no
   package install (same rule as ``Analysis``).
2. **Serials must never be emitted unquoted.** Every serial in this product is a
   digit string, and several carry leading zeros — ``0905260051`` (MFV),
   ``0701260010`` (MFH). Unquoted, a YAML reader parses those as integers and
   ``0905260051`` comes back as ``905260051``: a serial that matches nothing,
   silently, in the one file whose whole job is to be the record of which serial
   was where. ``28G5A00005`` survives; the pure-digit ones do not.

   A default dumper cannot be trusted to get this right for every field, so this
   writer quotes **every scalar that could be read as a number** and never
   guesses. Round-tripping is tested (``tests/test_yamlout.py``).

Ordering is insertion order throughout — no sorting, no aliases, no anchors —
so two snapshots of the same unit diff cleanly and a reviewer can see exactly
what changed on the line.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence

#: A scalar matching any of these would be re-read as something other than a
#: string, so it gets quoted. Numbers (including leading-zero and exponent
#: forms), booleans, nulls, and the YAML 1.1 y/n spellings.
_AMBIGUOUS = re.compile(
    r"""^(
        [-+]?\d+(\.\d*)?([eE][-+]?\d+)?   # 12, 0905260051, 1.5, 1e3
      | \.\d+([eE][-+]?\d+)?
      | 0[xXoObB][0-9a-fA-F_]+
      | [-+]?(\.inf|\.nan)
      | true|false|yes|no|on|off|y|n|null|~
      |                                    # the empty string
    )$""",
    re.X | re.I,
)

#: Characters that force quoting wherever they appear.
_NEEDS_QUOTE = re.compile(r"""[:#\[\]{},&*!|>'"%@`]|^[-?\s]|\s$|\n""")


def scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if _AMBIGUOUS.match(text) or _NEEDS_QUOTE.search(text):
        return "'" + text.replace("'", "''") + "'"
    return text


def _flow(mapping: Mapping[str, Any]) -> str:
    """One-line ``{k: v, ...}``. Used for test records: a test record is one
    fact and reads far better as one line than as five indented ones."""
    inner = ", ".join(f"{key}: {scalar(val)}" for key, val in mapping.items())
    return "{" + inner + "}"


def dump(data: Any, indent: int = 0, *, flow_lists: Sequence[str] = ()) -> List[str]:
    """Render ``data`` to YAML lines.

    ``flow_lists`` names keys whose list-of-dict values are emitted one record
    per line. Everything else nests normally.
    """
    pad = "  " * indent
    lines: List[str] = []

    if isinstance(data, Mapping):
        for key, value in data.items():
            if isinstance(value, Mapping):
                if not value:
                    lines.append(f"{pad}{key}: {{}}")
                else:
                    lines.append(f"{pad}{key}:")
                    lines.extend(dump(value, indent + 1, flow_lists=flow_lists))
            elif isinstance(value, (list, tuple)):
                if not value:
                    lines.append(f"{pad}{key}: []")
                    continue
                lines.append(f"{pad}{key}:")
                use_flow = key in flow_lists
                for item in value:
                    if isinstance(item, Mapping) and use_flow:
                        lines.append(f"{pad}  - {_flow(item)}")
                    elif isinstance(item, Mapping):
                        rendered = dump(item, indent + 2, flow_lists=flow_lists)
                        first = rendered[0].lstrip()
                        lines.append(f"{pad}  - {first}")
                        lines.extend(rendered[1:])
                    else:
                        lines.append(f"{pad}  - {scalar(item)}")
            else:
                lines.append(f"{pad}{key}: {scalar(value)}")
        return lines

    if isinstance(data, (list, tuple)):
        for item in data:
            if isinstance(item, Mapping):
                lines.append(f"{pad}- {_flow(item)}")
            else:
                lines.append(f"{pad}- {scalar(item)}")
        return lines

    return [f"{pad}{scalar(data)}"]


def dumps(data: Any, *, header: Sequence[str] = (), flow_lists: Sequence[str] = ()) -> str:
    out = [f"# {line}" for line in header]
    out.extend(dump(data, flow_lists=flow_lists))
    return "\n".join(out) + "\n"
