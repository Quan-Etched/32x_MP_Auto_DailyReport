#!/usr/bin/env python3
"""MCP server with one tool: rebuild Daily FA and copy it to the review host.

Stdio transport, stdlib only. Cursor launches this from ``.cursor/mcp.json``.
The tool calls ``review_refresh.refresh`` — the same function the 10:00
scheduled task runs — so a manual call and the morning run cannot drift.

Stdout is reserved for MCP frames. Progress from the rebuild goes to the
refresh log and to this process's stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_refresh  # noqa: E402

PROTOCOL = "2024-11-05"

TOOL = {
    "name": "refresh_review_server",
    "description": (
        "Download the latest controller data, rebuild Daily FA "
        "(dailyexcel.js and dailyfa.js), and copy both files to the "
        "review server production-failure-analysis. Run this on a machine "
        "that can reach pega; the review host cannot."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


def _read_message() -> dict | None:
    """One JSON-RPC message. Accepts LSP Content-Length frames or a JSON line."""
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    if line.lstrip().startswith(b"{"):
        return json.loads(line.decode("utf-8"))
    headers = {}
    while line not in (b"\r\n", b"\n"):
        if not line:
            return None
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
        line = sys.stdin.buffer.readline()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def _write_message(payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write("Content-Length: {}\r\n\r\n".format(len(body)).encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _result(msg_id, result: dict) -> None:
    _write_message({"jsonrpc": "2.0", "id": msg_id, "result": result})


def _error(msg_id, code: int, message: str) -> None:
    _write_message({
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    })


def _handle(message: dict) -> None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        version = (message.get("params") or {}).get("protocolVersion") or PROTOCOL
        _result(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "factory-review", "version": "1.0.0"},
        })
        return
    if method == "tools/list":
        _result(msg_id, {"tools": [TOOL]})
        return
    if method == "tools/call":
        name = (message.get("params") or {}).get("name")
        if name != TOOL["name"]:
            _error(msg_id, -32602, "unknown tool: {}".format(name))
            return
        code = review_refresh.refresh()
        text = "Review server updated." if code == 0 else (
            "Refresh failed with exit {}.".format(code)
        )
        _result(msg_id, {
            "content": [{"type": "text", "text": text}],
            "isError": code != 0,
        })
        return
    if method == "ping" and msg_id is not None:
        _result(msg_id, {})
        return
    if msg_id is not None and method:
        _error(msg_id, -32601, "method not found: {}".format(method))


def main() -> int:
    while True:
        message = _read_message()
        if message is None:
            return 0
        try:
            _handle(message)
        except Exception as exc:  # noqa: BLE001 — keep the stdio session alive
            msg_id = message.get("id")
            if msg_id is not None:
                _error(msg_id, -32603, str(exc))
            print("review_mcp: {}".format(exc), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
