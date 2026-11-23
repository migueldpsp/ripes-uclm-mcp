# ripes-uclm-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant
such as Claude operate the **UCLM Ripes** RISC-V simulator on Windows. The
assistant can write and assemble programs, configure the processor and cache
hierarchy, run and step the simulation, set breakpoints, and read registers,
memory, pipeline state and cache statistics. Every action is carried out in
the regular Ripes window and is visible as it happens.

The server works with the official, unmodified Ripes binary. No patch, plugin
or rebuild of Ripes is required.

## Who it is for

- **Teachers:** prepare and check lab exercises, reproduce student results,
  generate example programs, compare processor or cache configurations, and
  demonstrate concepts live in class.
- **Students:** explore how a program behaves on each datapath, ask
  questions while the simulation runs, and check results and analyses.
- **Anyone working with RISC-V and computer architecture** who wants to
  automate repetitive simulation runs in Ripes.

## Features

- **Code:** write, load and save assembly; report assembler errors; show the
  disassembled or binary program.
- **Simulation:** reset, step forward and backward by cycles, run until a
  breakpoint or the end of the program, and auto-clock at a chosen speed.
- **Inspection:** registers, data memory, memory map, console output, cycles,
  CPI/IPC, and the pipeline stage of every instruction.
- **Breakpoints:** set, list and clear them.
- **Processor configuration:** single-cycle, multicycle (one or two
  memories), 5-stage pipelined with or without forwarding and hazard
  detection, branch strategies, and dual issue; RV32/RV64; M and C
  extensions.
- **Cache configuration:** L1 split, L1 unified and multilevel organisations,
  with ways, sets, block size and replacement and write policies; hits,
  misses, hit rate and writebacks per cache.
- **Screenshots** of the Ripes window, for example to examine the datapath.
- **Headless runs** through the Ripes command line, without touching the
  window. They report registers, cycles, CPI and the full pipeline diagram.

## Requirements

| Requirement | Version |
| --- | --- |
| Windows | 10 or 11 |
| Python | 3.10 or newer |
| UCLM Ripes | v1.1 for Windows ([UCLM-Ripes](https://github.com/silvigon/UCLM-Ripes)) |
| MCP client | Claude Code, Claude Desktop or any other MCP-compatible client |

The server relies on Windows UI Automation, so it does not run on Linux or
macOS.

## Installation

Installation takes three steps. No clone of the repository is needed.

### 1. Install the Python dependencies

```powershell
pip install "git+https://github.com/migueldpsp/ripes-uclm-mcp.git"
```

This installs the `ripes_mcp` package and its dependencies (`mcp`,
`pywinauto`, `pywin32` and `pillow`) into the Python that runs as `python`.
The MCP server is started with that same command, so install into the Python
that is first on your `PATH`.

### 2. Tell the server where Ripes is

The server looks for `Ripes.exe` in this order:

1. The `RIPES_PATH` environment variable.
2. The `Ripes.exe` of a Ripes window that is already open.

Setting `RIPES_PATH` is recommended, because it lets the server start Ripes
by itself. Use your own installation path:

```powershell
setx RIPES_PATH "C:\path\to\UCLM_Ripes-v1.1-win-x86_64\Ripes.exe"
```

`setx` only affects programs started afterwards.

### 3. Install the plugin in Claude

The repository is a Claude Code **plugin** that bundles the MCP server and a
skill (`skills/ripes`) describing the recommended workflow to the assistant.
Once installed, it is available in every session, in Claude Code and in the
Code tab of the Claude desktop app.

```powershell
claude plugin marketplace add migueldpsp/ripes-uclm-mcp
```

```powershell
claude plugin install ripes-uclm@ripes-uclm
```

Without the `claude` command line, add the same entries to
`%USERPROFILE%\.claude\settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "ripes-uclm": {
      "source": { "source": "github", "repo": "migueldpsp/ripes-uclm-mcp" }
    }
  },
  "enabledPlugins": {
    "ripes-uclm@ripes-uclm": true
  }
}
```

Fully close and reopen Claude (or start a new Claude Code session). The
server appears as `ripes` in the list of connectors.

### Checking the installation

Open Ripes and ask the assistant *"What is the Ripes status?"*. It should
answer with the processor model shown in the Ripes status bar. In Claude
Code, `/mcp` also lists the server as connected.

### Other MCP clients

Any MCP client can start the server with `python -m ripes_mcp`. For chats in
Claude Desktop, add it to `claude_desktop_config.json` (Settings → Developer
→ Edit Config) and restart:

```json
{
  "mcpServers": {
    "ripes": {
      "command": "python",
      "args": ["-m", "ripes_mcp"],
      "env": { "RIPES_PATH": "C:\\path\\to\\Ripes.exe" }
    }
  }
}
```

### Development setup

To work on the code, clone the repository and install it in editable mode:

```powershell
git clone https://github.com/migueldpsp/ripes-uclm-mcp.git
cd ripes-uclm-mcp
pip install -e .
```

Inside the repository, the root `.mcp.json` also works as a project-level
server without installing the plugin.

## Usage

Describe the task in plain language. The assistant chooses the tools. Some
examples:

- *"Write a program that adds the elements of an array and run it in Ripes."*
- *"Switch to the 5-stage pipelined processor without forwarding, run the
  program and explain every stall."*
- *"Set a breakpoint on the store, run until it stops and show t0–t2 and the
  `.data` section."*
- *"Step three cycles and tell me which instruction is in each pipeline
  stage."*
- *"Compare the CPI of this program on the single-cycle, multicycle and
  pipelined processors."*
- *"Configure a two-level cache (L1: 512 B, 16 B blocks, 2-way; L2: 4 KB,
  256 B blocks, 4-way), run the program and report local and global hit
  rates."*
- *"Load `exercise.s`, find the bug and fix it."*

## Tool reference

| Area | Tools |
| --- | --- |
| Window | `ripes_launch`, `ripes_status`, `ripes_screenshot`, `ripes_show_tab` |
| Editor | `ripes_set_source`, `ripes_get_source`, `ripes_get_program`, `ripes_set_view_mode`, `ripes_load_file`, `ripes_save_source` |
| Simulation | `ripes_reset`, `ripes_step`, `ripes_step_back`, `ripes_run`, `ripes_auto_clock`, `ripes_get_execution_info` |
| Inspection | `ripes_get_registers`, `ripes_get_instruction_memory`, `ripes_get_console`, `ripes_clear_console`, `ripes_read_memory`, `ripes_get_memory_map` |
| Breakpoints | `ripes_set_breakpoint`, `ripes_list_breakpoints`, `ripes_clear_breakpoints` |
| Processor and cache | `ripes_select_processor`, `ripes_select_cache`, `ripes_get_cache_info`, `ripes_configure_cache` |
| Headless | `ripes_cli_run`, `ripes_check_assembly` |

Each tool's parameters are documented in its MCP description, which the
client shows to the assistant.

## How it works

| Mechanism | Purpose |
| --- | --- |
| Windows UI Automation | Ripes is a Qt 6 application, and Qt exposes every widget through UI Automation. The server reads tables (registers, instruction memory, memory viewer, cache statistics) and edits the code editor through it. |
| Window messages | Controls that open dialogs (processor and cache selection, *Go to address*) and the tab bar receive clicks posted to the Ripes window. The user's mouse cursor is not moved. |
| Ripes command line | `Ripes.exe --mode cli` checks for assembler errors, which the window only underlines, and performs headless runs. |
| Window capture | Breakpoint check boxes do not report their state through UI Automation, so their state is read from the window image. |

Code layout:

| File | Contents |
| --- | --- |
| `src/ripes_mcp/server.py` | MCP tool definitions |
| `src/ripes_mcp/controller.py` | High-level Ripes operations |
| `src/ripes_mcp/uia.py` | UI Automation, input and capture helpers |
| `src/ripes_mcp/cli_runner.py` | Ripes command-line runs |
| `skills/ripes/SKILL.md` | Workflow guidance for the assistant |
| `.claude-plugin/`, `.mcp.json` | Plugin, marketplace and MCP server definitions |

## Limitations

- Windows only.
- Developed and tested with UCLM Ripes v1.1. Other Ripes versions may change
  widget names or dialogs.
- Processor and cache selections are saved in the Ripes settings, exactly as
  when they are chosen by hand.
- Reading some data brings the corresponding tab to the front (for example,
  the Memory tab to read memory).
- Only the first assembler error is reported.
- A minimised Ripes window is restored, because posted clicks need visible
  window coordinates.
- Breakpoint detection assumes a blue Windows accent colour.
- Editing register values by hand and the I/O tab are not supported yet.

## Troubleshooting

| Symptom | Solution |
| --- | --- |
| The assistant has no `ripes_*` tools | Check that the plugin is installed and enabled, that step 1 succeeded for the Python on your `PATH`, and fully restart Claude. |
| `Ripes.exe not found` | Open Ripes, or set `RIPES_PATH` and restart Claude. |
| `Ripes is not running` | Ask the assistant to launch Ripes (requires `RIPES_PATH`) or open it manually. |
| A Ripes dialog remains open | Close it with *Cancel* and repeat the request. |
| Breakpoints are not detected | Use a blue accent colour in Windows. |

## Testing

With Ripes open, or with `RIPES_PATH` set:

```powershell
python tests/smoke_mcp.py
```

The test connects to the server as an MCP client and checks the main
features in a live Ripes window: assembler errors, breakpoints, registers,
console, memory, reverse stepping, screenshots and a headless pipelined run.
When it finishes, Ripes is left on the single-cycle processor with an L1
split cache.

## Acknowledgements

- [Ripes](https://github.com/mortbopet/Ripes) by Morten Borup Petersen.
- [UCLM-Ripes](https://github.com/silvigon/UCLM-Ripes), the Universidad de
  Castilla-La Mancha fork that adds multicycle processors and cache
  organisations.
