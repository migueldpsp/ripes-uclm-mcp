"""End-to-end smoke test: starts the MCP server over stdio and drives a live Ripes.

Run from the repository root with Ripes open (or with RIPES_PATH set, so the
server can launch it):

    python tests/smoke_mcp.py

It leaves Ripes on the single-cycle processor with an L1 split cache.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

PROGRAM = """.data
v: .word 5, 7, 0
.text
main:
    la t0, v
    lw t1, 0(t0)
    lw t2, 4(t0)
    add t3, t1, t2
    sw t3, 8(t0)
    mv a0, t3
    li a7, 1
    ecall
    li a7, 10
    ecall
"""


def payload(result):
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        raise AssertionError(f"tool error: {result.content}")
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured is not None:
        return structured.get("result", structured)
    def parse(item):
        if getattr(item, "type", "") != "text":
            return item
        try:
            return json.loads(item.text)
        except json.JSONDecodeError:
            return item.text

    if not result.content:
        return []
    if len(result.content) > 1:  # lists may come back as one content item per element
        return [parse(i) for i in result.content]
    return parse(result.content[0])


async def main() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    params = StdioServerParameters(command=sys.executable, args=["-m", "ripes_mcp"],
                                   env=env, cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"{len(tools)} tools:", ", ".join(tools))

            async def call(name, **args):
                return payload(await session.call_tool(name, args))

            await call("ripes_launch")
            print("processor:", (await call("ripes_select_processor", preset="RV32_SS"))["processor"])
            await call("ripes_select_cache", cache_type="l1_split")

            bad = await call("ripes_set_source", code="main:\n    addx a0, a1\n")
            assert not bad["assembled"] and bad["errors"], bad
            print("assembler error reported:", bad["errors"][-1])

            res = await call("ripes_set_source", code=PROGRAM)
            assert res["assembled"], res
            await call("ripes_reset")
            await call("ripes_clear_breakpoints")
            await call("ripes_set_breakpoint", address="0x14")
            stop = await call("ripes_run", timeout_seconds=10)
            assert stop["stopped_by"] == "breakpoint", stop
            at = [r for r in await call("ripes_get_instruction_memory") if r["stage"]]
            print("stopped at:", at)
            assert at and at[0]["address"] == "0x14"

            stop = await call("ripes_run", timeout_seconds=10)
            assert stop["stopped_by"] == "finished", stop
            regs = {r["alias"]: r.get("unsigned") for r in (await call("ripes_get_registers"))["registers"]}
            assert regs["a0"] == 12 and regs["t1"] == 5 and regs["t2"] == 7, regs
            console = await call("ripes_get_console")
            assert "12" in console, console
            mem = await call("ripes_read_memory", address="0x10000000", words=3)
            assert [m["unsigned"] for m in mem] == [5, 7, 12], mem
            print("registers, console and memory OK")

            back = await call("ripes_step_back", cycles=2)
            print("reverse:", back)
            await call("ripes_clear_breakpoints")

            shot = await session.call_tool("ripes_screenshot", {})
            assert shot.content[0].type == "image", shot.content[0].type
            print("screenshot bytes (base64):", len(shot.content[0].data))

            cli = await call("ripes_cli_run", code=PROGRAM, processor="RV32_5S")
            assert cli["ok"] and cli["report"]["registers"]["x10"] == 12, cli
            print("CLI 5-stage run: cycles", cli["report"]["cycles"], "CPI", cli["report"]["CPI"])
            print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
