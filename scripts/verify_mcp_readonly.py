"""Verify the restricted Alpaca MCP profile and make one live read-only call."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER_COMMAND = (
    "uvx",
    "--with",
    "fastmcp==3.1.0",
    "alpaca-mcp-server==2.2.0",
    "--env-file",
    str(ROOT / ".env"),
)
READ_ONLY_TOOLSETS = "assets,stock-data,options-data"
READ_ONLY_PREFIXES = ("get_", "list_", "search_", "fetch_")
WRITE_TERMS = (
    "order",
    "position",
    "account",
    "watchlist",
    "exercise",
    "close",
    "cancel",
    "replace",
)


class McpProbeError(RuntimeError):
    pass


def _read_json_line(process: subprocess.Popen[str], *, timeout: int = 30) -> dict[str, Any]:
    if process.stdout is None:
        raise McpProbeError("MCP stdout is unavailable")
    queue: Queue[str] = Queue(maxsize=1)

    def read_one() -> None:
        queue.put(process.stdout.readline())

    Thread(target=read_one, daemon=True).start()
    try:
        line = queue.get(timeout=timeout)
    except Empty as exc:
        raise McpProbeError("timed out waiting for an MCP response") from exc
    if not line:
        raise McpProbeError("MCP server closed before returning a response")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise McpProbeError("MCP server returned malformed JSON-RPC") from exc
    if not isinstance(payload, dict):
        raise McpProbeError("MCP response must be a JSON object")
    return payload


def _send(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise McpProbeError("MCP stdin is unavailable")
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def run_probe() -> dict[str, object]:
    child_environment = os.environ.copy()
    child_environment["ALPACA_TOOLSETS"] = READ_ONLY_TOOLSETS
    child_environment["ALPACA_PAPER_TRADE"] = "true"
    process = subprocess.Popen(  # noqa: S603
        SERVER_COMMAND,
        cwd=ROOT,
        env=child_environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    try:
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "conviction-spread-verifier",
                        "version": "0.1",
                    },
                },
            },
        )
        initialized = _read_json_line(process)
        if initialized.get("id") != 1 or "result" not in initialized:
            raise McpProbeError("MCP initialization failed")
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        _send(
            process,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        registry = _read_json_line(process)
        tools = registry.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise McpProbeError("MCP tool registry is unavailable")
        names = sorted(
            str(tool.get("name"))
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        )
        write_like = [
            name for name in names if any(term in name.lower() for term in WRITE_TERMS)
        ]
        non_read_prefix = [
            name for name in names if not name.lower().startswith(READ_ONLY_PREFIXES)
        ]
        if write_like or non_read_prefix:
            raise McpProbeError(
                "restricted MCP profile exposed a non-read-shaped tool: "
                f"named={write_like}, prefixes={non_read_prefix}"
            )
        _send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_stock_snapshot",
                    "arguments": {"symbols": "SPY", "feed": "iex"},
                },
            },
        )
        call = _read_json_line(process)
        if call.get("id") != 3 or "result" not in call:
            raise McpProbeError("MCP stock snapshot call failed")
        call_result = call["result"]
        serialized_result = json.dumps(
            call_result, sort_keys=True, separators=(",", ":")
        ).encode()
        content = call_result.get("content", []) if isinstance(call_result, dict) else []
        content_types = sorted(
            {
                str(block.get("type"))
                for block in content
                if isinstance(block, dict) and block.get("type")
            }
        )
        is_error = bool(call_result.get("isError")) if isinstance(call_result, dict) else True
        if is_error:
            raise McpProbeError("MCP stock snapshot tool returned an error result")

        server_info = initialized["result"].get("serverInfo", {})
        return {
            "schema_version": "phase-5a.mcp-proof.v1",
            "server_package": "alpaca-mcp-server==2.2.0",
            "fastmcp_pin": "3.1.0",
            "protocol_version": initialized["result"].get("protocolVersion"),
            "server_name": server_info.get("name"),
            "toolsets_requested": READ_ONLY_TOOLSETS.split(","),
            "tool_count": len(names),
            "write_or_account_named_tools": write_like,
            "non_read_prefix_tools": non_read_prefix,
            "tools": names,
            "live_call": {
                "tool": "get_stock_snapshot",
                "arguments": {"symbols": "SPY", "feed": "iex"},
                "succeeded": True,
                "content_types": content_types,
                "response_sha256": hashlib.sha256(serialized_result).hexdigest(),
                "raw_market_response_committed": False,
            },
            "safety": {
                "paper_mode": True,
                "trading_toolset_requested": False,
                "credentials_emitted": False,
                "account_data_requested": False,
            },
        }
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the read-only Alpaca MCP profile.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if not (ROOT / ".env").exists():
        print("MCP probe requires the ignored repository .env", file=sys.stderr)
        return 2
    try:
        result = run_probe()
    except (McpProbeError, OSError) as exc:
        print(f"MCP probe failed safely: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
