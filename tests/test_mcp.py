# -*- coding: utf-8 -*-
"""MCP JSON-RPC server: stdout must stay a clean protocol stream."""

import json
import subprocess
import sys


def _rpc(*requests):
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    proc = subprocess.run(
        [sys.executable, "-m", "ableton_agent.cli", "mcp"],
        input=payload, capture_output=True, text=True, timeout=90,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines], proc.stderr


def test_initialize_and_tools_list():
    responses, _ = _rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert responses[0]["result"]["serverInfo"]["name"]
    names = [t["name"] for t in responses[1]["result"]["tools"]]
    assert "ableton_plan_and_run" in names


def test_get_status_is_json_serializable():
    responses, _ = _rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "ableton_get_status", "arguments": {}}})
    result = responses[0]["result"]
    assert result["isError"] is False
    status = json.loads(result["content"][0]["text"])
    assert isinstance(status["llm_endpoint"], str)
    assert status["bridge_connected"] is False


def test_dry_run_planning_never_pollutes_stdout():
    responses, _ = _rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "ableton_plan_and_run",
                                    "arguments": {"prompt": "techno at 130 bpm",
                                                  "dry_run": True}}})
    assert len(responses) == 1
    plan = json.loads(responses[0]["result"]["content"][0]["text"])
    assert plan["status"] == "planned"
    assert plan["commands_count"] > 0


def test_unknown_method_returns_error():
    responses, _ = _rpc({"jsonrpc": "2.0", "id": 1, "method": "nope", "params": {}})
    assert responses[0]["error"]["code"] == -32601


def test_notifications_get_no_response():
    responses, _ = _rpc(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}},
    )
    assert [r["id"] for r in responses] == [9]
