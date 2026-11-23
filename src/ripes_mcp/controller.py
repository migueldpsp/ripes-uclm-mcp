"""High-level control of a running (unmodified) UCLM Ripes window."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from . import uia
from .cli_runner import check_assembly, ripes_exe
from .uia import RipesError

TABS = ["editor", "processor", "cache", "memory", "io"]
TAB_WIDGET_IDS = {
    "Ripes__EditTab": "editor",
    "Ripes__ProcessorTab": "processor",
    "Ripes__CacheTab": "cache",
    "Ripes__MemoryTab": "memory",
    "Ripes__IOTab": "io",
}

# Geometry of Ripes' FancyTabBar (external/fancytabbar), in logical pixels.
TABBAR_LOGICAL_WIDTH = 80
TAB_HEIGHT = 55

# Toolbar action names, exactly as Ripes labels them.
BTN_SELECT_PROCESSOR = "Select processor"
BTN_SELECT_CACHE = "Select cache"
BTN_RESET = "Reset (F3)"
BTN_REVERSE = "Reverse (F4)"
BTN_CLOCK = "Clock (F5)"
BTN_AUTO_CLOCK = "Auto clock (F6)"
BTN_RUN = "Run (F8)"

DATAPATHS = {
    "single": "Single-stage",
    "multicycle_1m": "Five-stage multicycle (single memory)",
    "multicycle_2m": "Five-stage multicycle (separate memories)",
    "pipelined": "Five-stage pipelined",
    "dual_issue": "Six-stage dual-issue superscalar",
}
BRANCH_STRATEGIES = {
    "not_applicable": "Not applicable",
    "predict_not_taken": "Predict not taken",
    "delayed_branch": "Delayed branch",
}

# Processor IDs (same names as the Ripes CLI) -> settings of the selection dialog.
# Source: src/processorregistry.cpp in UCLM-Ripes v1.1.
PROCESSOR_PRESETS = {
    "SS": ("single", None, 0, False, False),
    "5MC_1M": ("multicycle_1m", None, 0, False, False),
    "5MC_2M": ("multicycle_2m", None, 0, False, False),
    "5S_NO_FW_HZ": ("pipelined", "predict_not_taken", 2, False, False),
    "5S_NO_FW": ("pipelined", "predict_not_taken", 2, False, True),
    "5S_NO_HZ": ("pipelined", "predict_not_taken", 2, True, False),
    "5S": ("pipelined", "predict_not_taken", 2, True, True),
    "5S_1S": ("pipelined", "predict_not_taken", 1, True, True),
    "5S_3S": ("pipelined", "predict_not_taken", 3, True, True),
    "5S_1S_DB": ("pipelined", "delayed_branch", 1, True, True),
    "5S_2S_DB": ("pipelined", "delayed_branch", 2, True, True),
    "5S_3S_DB": ("pipelined", "delayed_branch", 3, True, True),
    "6S_DUAL": ("dual_issue", "predict_not_taken", 3, True, True),
}

CACHE_TYPES = {
    "l1_split": "L1 Split Cache",
    "l1_unified": "L1 Unified Cache",
    "multilevel": "Multilevel Cache",
}


def _parse_reg(text: str) -> int | None:
    try:
        return int(text, 0)
    except ValueError:
        return None


class RipesController:
    def __init__(self) -> None:
        self._last_launch: subprocess.Popen | None = None

    # ------------------------------------------------------------------ window

    def window(self, launch: bool = False) -> uia.UIAWrapper:
        w = uia.find_main_window()
        if w is None and launch:
            self.launch()
            w = uia.find_main_window()
        if w is None:
            raise RipesError("Ripes is not running. Call ripes_launch first.")
        return w

    def launch(self) -> dict:
        if uia.find_main_window() is not None:
            return {"launched": False, "message": "Ripes was already running"}
        exe = ripes_exe()
        self._last_launch = subprocess.Popen([str(exe)], cwd=exe.parent)
        if not uia.wait_until(uia.find_main_window, timeout=30, interval=0.5):
            raise RipesError("Ripes did not open its main window within 30 s")
        time.sleep(1.0)  # let Qt finish building the initial tabs
        return {"launched": True, "pid": self._last_launch.pid}

    def screenshot(self) -> bytes:
        return uia.capture_window_png(self.window().handle)

    def _dialog(self, title: str, timeout: float = 5.0) -> uia.UIAWrapper:
        pid = self.window().process_id()
        dlg = uia.wait_until(lambda: uia.find_window_by_title(pid, title), timeout)
        if dlg is None:
            raise RipesError(f"Dialog '{title}' did not appear")
        # Wait until Qt has populated the dialog's accessibility tree.
        uia.wait_until(lambda: len(dlg.children()) > 1, timeout)
        return dlg

    def _toolbar_button(self, name: str) -> uia.UIAWrapper:
        return uia.find_one(self.window(), f"toolbar button '{name}'", name=name)

    # -------------------------------------------------------------------- tabs

    def current_tab(self) -> str:
        w = self.window()
        stack = uia.find_one(w, "central stack", class_name="QStackedWidget")
        for child in stack.children():
            tab = TAB_WIDGET_IDS.get(uia.auto_id(child))
            if tab:
                return tab
        return "unknown"

    def show_tab(self, tab: str) -> str:
        if tab not in TABS:
            raise ValueError(f"tab must be one of {TABS}")
        if self.current_tab() == tab:
            return tab
        w = self.window()
        bar = uia.find_one(w, "tab bar", id_suffix="centralwidget.tabbar")
        r = bar.rectangle()
        scale = r.width() / TABBAR_LOGICAL_WIDTH
        index = TABS.index(tab)
        x = (r.left + r.right) // 2
        y = r.top + int((index * TAB_HEIGHT + 1 + TAB_HEIGHT // 2) * scale)
        uia.post_click_at(w.handle, x, y)
        if not uia.wait_until(lambda: self.current_tab() == tab, timeout=3):
            raise RipesError(f"Could not switch to the {tab} tab")
        return tab

    def _in_tab(self, tab: str) -> uia.UIAWrapper:
        """Show ``tab`` and return its root widget."""
        self.show_tab(tab)
        widget_id = next(k for k, v in TAB_WIDGET_IDS.items() if v == tab)
        return uia.find_one(self.window(), f"{tab} tab", id_suffix=widget_id)

    def _tab_with_registers(self) -> uia.UIAWrapper:
        tab = self.current_tab()
        return self._in_tab(tab if tab in ("editor", "processor") else "processor")

    # ------------------------------------------------------------------ status

    def status(self) -> dict:
        w = self.window()
        labels = [t.window_text() for t in uia.find_all(w, control_type="Text")
                  if t.window_text().startswith("Processor:")]
        clock = self._toolbar_button(BTN_CLOCK)
        run = self._toolbar_button(BTN_RUN)
        auto = self._toolbar_button(BTN_AUTO_CLOCK)
        status = {
            "processor": labels[0] if labels else None,
            "current_tab": self.current_tab(),
            "running": uia.toggle_state(run),
            "auto_clocking": uia.toggle_state(auto),
            "finished": not uia.is_enabled(clock) and not uia.toggle_state(run)
            and not uia.toggle_state(auto),
            "can_reverse": uia.is_enabled(self._toolbar_button(BTN_REVERSE)),
        }
        if status["current_tab"] == "processor":
            status["execution"] = self.execution_info()
        return status

    # ------------------------------------------------------------------ editor

    def get_source(self) -> str:
        tab = self._in_tab("editor")
        return uia.text_of(uia.find_one(tab, "code editor", id_suffix=".codeEditor"))

    def get_program(self) -> str:
        """Disassembly (or binary, depending on the view mode) of the loaded program."""
        tab = self._in_tab("editor")
        return uia.text_of(uia.find_one(tab, "program viewer", id_suffix=".programViewer"))

    def set_source(self, code: str, wait: float = 4.0) -> dict:
        """Replace the editor contents; Ripes re-assembles automatically."""
        tab = self._in_tab("editor")
        asm_radio = uia.find_one(tab, "Assembly radio button", id_suffix=".setAssemblyInput")
        if not asm_radio.is_selected():
            asm_radio.select()
            time.sleep(0.3)
        editor = uia.find_one(tab, "code editor", id_suffix=".codeEditor")
        viewer = uia.find_one(tab, "program viewer", id_suffix=".programViewer")
        before = uia.text_of(viewer)
        editor.iface_value.SetValue(code)

        check = check_assembly(code, isa_extensions=self._isa_extensions_hint())
        program = None
        if check["assembled"]:
            # Wait for Ripes to re-assemble (unchanged if the machine code is identical).
            uia.wait_until(lambda: uia.text_of(viewer) != before, timeout=wait)
            program = uia.text_of(viewer)
        return {"assembled": check["assembled"], "errors": check["errors"], "program": program}

    def _isa_extensions_hint(self) -> str:
        w = self.window()
        for t in uia.find_all(w, control_type="Text"):
            text = t.window_text()
            if "ISA:" in text:
                isa = text.split("ISA:")[1].strip()  # e.g. RV32IM / RV32IMC
                return ",".join(isa[5:]) if len(isa) > 5 else ""
        return "M"

    def set_view_mode(self, mode: str) -> None:
        tab = self._in_tab("editor")
        suffix = {"disassembled": ".disassembledViewButton", "binary": ".binaryViewButton"}[mode]
        uia.find_one(tab, f"{mode} radio", id_suffix=suffix).select()

    # -------------------------------------------------------------- simulation

    def reset(self) -> dict:
        btn = self._toolbar_button(BTN_RESET)
        self._stop_continuous()
        btn.invoke()
        time.sleep(0.2)
        return self.status()

    def _stop_continuous(self) -> None:
        for name in (BTN_RUN, BTN_AUTO_CLOCK):
            b = self._toolbar_button(name)
            if uia.toggle_state(b):
                uia.toggle(b)
                time.sleep(0.2)

    def clock(self, steps: int = 1) -> dict:
        btn = self._toolbar_button(BTN_CLOCK)
        done = 0
        for _ in range(steps):
            if not uia.is_enabled(btn):
                break
            btn.invoke()
            done += 1
        time.sleep(0.05)
        return {"steps_done": done, "finished": not uia.is_enabled(btn)}

    def reverse(self, steps: int = 1) -> dict:
        btn = self._toolbar_button(BTN_REVERSE)
        done = 0
        for _ in range(steps):
            if not uia.is_enabled(btn):
                break
            btn.invoke()
            done += 1
        return {"steps_done": done, "can_reverse": uia.is_enabled(btn)}

    def run(self, timeout: float = 10.0) -> dict:
        """Run until the program exits, hits a breakpoint or ``timeout`` expires."""
        run = self._toolbar_button(BTN_RUN)
        clock = self._toolbar_button(BTN_CLOCK)
        if uia.toggle_state(self._toolbar_button(BTN_AUTO_CLOCK)):
            uia.toggle(self._toolbar_button(BTN_AUTO_CLOCK))
            time.sleep(0.2)
        if not uia.is_enabled(run):
            return {"stopped_by": "already_finished", **self.status()}
        # Ripes' Run stops at once if the current PC holds a breakpoint, so
        # step over it first: this makes run() behave like "continue".
        clock.invoke()
        if not uia.is_enabled(clock):
            return {"stopped_by": "finished", **self.status()}
        uia.toggle(run)
        stopped = uia.wait_until(lambda: not uia.toggle_state(run), timeout, interval=0.1)
        if not stopped:
            uia.toggle(run)  # stop it ourselves
            uia.wait_until(lambda: not uia.toggle_state(run), 3)
            reason = "timeout"
        elif not uia.is_enabled(clock):
            reason = "finished"
        else:
            reason = "breakpoint"
        time.sleep(0.2)
        return {"stopped_by": reason, **self.status()}

    def auto_clock(self, enable: bool, interval_ms: int | None = None) -> dict:
        w = self.window()
        if interval_ms is not None:
            toolbar = uia.find_one(w, "simulator toolbar", name="Simulator control",
                                   control_type="ToolBar")
            spinner = uia.find_one(toolbar, "auto clock interval", class_name="QSpinBox")
            spinner.iface_range_value.SetValue(float(interval_ms))
        btn = self._toolbar_button(BTN_AUTO_CLOCK)
        if uia.toggle_state(btn) != enable:
            uia.toggle(btn)
        return self.status()

    def execution_info(self) -> dict:
        tab = self._in_tab("processor")
        out = {}
        for key in ("cycleCount", "instructionsRetired", "cpi", "ipc", "clockRate"):
            found = uia.find_all(tab, id_suffix="groupBox_2." + key)
            out[key] = uia.value_of(found[0]) if found else None
        return {"cycles": out["cycleCount"], "instructions_retired": out["instructionsRetired"],
                "cpi": out["cpi"], "ipc": out["ipc"], "clock_rate": out["clockRate"]}

    # -------------------------------------------------------------- registers

    def registers(self) -> dict:
        tab = self._tab_with_registers()
        tables = uia.find_all(tab, id_suffix=".registerView")
        if not tables:
            raise RipesError("Register view not found")
        rows = uia.read_grid(tables[0])
        radix = uia.find_all(tab, id_suffix="radixSelector.displayType")
        regs = []
        for name, alias, value in rows:
            entry = {"name": name, "alias": alias, "value": value}
            num = _parse_reg(value)
            if num is not None:
                entry["unsigned"] = num
            regs.append(entry)
        return {"display_type": uia.value_of(radix[0]) if radix else None, "registers": regs}

    # ------------------------------------------------------ instruction memory

    def _instruction_table(self) -> tuple[uia.UIAWrapper, int]:
        tab = self._in_tab("processor")
        table = uia.find_one(tab, "instruction memory view", id_suffix=".instructionView")
        header = [h for h in table.children(control_type="Header") if h.window_text() == "BP"]
        header_bottom = header[0].rectangle().bottom if header else table.rectangle().top
        return table, header_bottom

    def _breakpoint_at_row(self, table: uia.UIAWrapper, header_bottom: int, row: int) -> bool:
        cell = uia.ensure_cell_visible(table, row, 0, header_bottom)
        return uia.is_checkbox_checked(uia.top_level_hwnd(cell), cell.rectangle())

    def instruction_memory(self, include_breakpoints: bool = False) -> list[dict]:
        """Rows of the 'Instruction memory' panel; ``stage`` shows where each
        instruction currently is in the datapath (IF/ID/EX/MEM/WB...)."""
        table, header_bottom = self._instruction_table()
        out = []
        for r, (_bp, addr, stage, instr) in enumerate(uia.read_grid(table)):
            row = {"address": addr, "stage": stage, "instruction": instr}
            if include_breakpoints:
                row["breakpoint"] = self._breakpoint_at_row(table, header_bottom, r)
            out.append(row)
        return out

    def breakpoints(self) -> list[str]:
        return [r["address"] for r in self.instruction_memory(include_breakpoints=True)
                if r["breakpoint"]]

    def set_breakpoint(self, address: int, enabled: bool = True) -> dict:
        table, header_bottom = self._instruction_table()
        for r, (addr,) in enumerate(uia.read_grid(table, columns=[1])):
            if _parse_reg(addr) == address:
                if self._breakpoint_at_row(table, header_bottom, r) != enabled:
                    # A click on the cell flips the breakpoint (the UIA Toggle
                    # action is accepted by Qt but ignored by Ripes' model).
                    uia.post_click(uia.ensure_cell_visible(table, r, 0, header_bottom))
                    uia.wait_until(lambda: self._breakpoint_at_row(table, header_bottom, r)
                                   == enabled, timeout=1.5, interval=0.1)
                state = self._breakpoint_at_row(table, header_bottom, r)
                if state != enabled:
                    raise RipesError(f"Could not change the breakpoint at {address:#x}")
                return {"address": hex(address), "breakpoint": state}
        raise RipesError(f"No instruction at address {address:#x}")

    def clear_breakpoints(self) -> list[str]:
        cleared = self.breakpoints()
        for addr in cleared:
            self.set_breakpoint(int(addr, 0), False)
        return cleared

    # ----------------------------------------------------------------- console

    def console(self) -> str:
        tab = self._tab_with_registers()
        edits = [e for e in uia.find_all(tab, id_suffix=".console", class_name="Ripes::Console")]
        return uia.text_of(edits[0]) if edits else ""

    def clear_console(self) -> None:
        tab = self._tab_with_registers()
        uia.find_one(tab, "clear console button", id_suffix=".clearConsoleButton").invoke()

    # ------------------------------------------------------------------ memory

    def memory_map(self) -> list[dict]:
        tab = self._in_tab("memory")
        table = uia.find_one(tab, "memory map", id_suffix=".memoryMapView")
        return [{"name": n, "size": s, "range": rng} for n, s, rng in uia.read_grid(table)]

    def _memory_rows(self, tab: uia.UIAWrapper) -> dict[int, dict]:
        table = uia.find_one(tab, "memory view", id_suffix=".memoryView")
        rows = {}
        for addr, word, *bytes_ in uia.read_grid(table):
            a = _parse_reg(addr)
            if a is not None:
                rows[a] = {"word": word, "bytes": bytes_}
        return rows

    def _goto_address(self, tab: uia.UIAWrapper, address: int) -> None:
        """Use the memory viewer's 'Go to section → Address...' dialog."""
        combos = uia.find_all(tab, class_name="Ripes::GoToComboBox")
        labels = [t for t in uia.find_all(tab, control_type="Text")
                  if t.window_text().startswith("Go to section")]
        if not combos:
            raise RipesError("Memory 'Go to' combo boxes not found")
        combo = combos[0]
        if labels:  # pick the combo closest (to the right) of the "Go to section" label
            lr = labels[0].rectangle()
            combo = min(combos, key=lambda c: abs(c.rectangle().top - lr.top)
                        + abs(c.rectangle().left - lr.right))
        pid = self.window().process_id()
        uia.post_click(combo)
        popup_item = uia.wait_until(lambda: self._find_popup_item(pid, "Address..."), 3)
        if popup_item is None:
            uia.post_key(self.window().handle, 0x1B)  # Esc
            raise RipesError("Could not open the 'Go to section' list")
        uia.post_click(popup_item)
        dlg = self._find_address_dialog(pid)
        edit = uia.find_one(dlg, "address field", class_name="QLineEdit")
        edit.iface_value.SetValue(f"0x{address:08x}")
        time.sleep(0.1)
        ok = uia.find_one(dlg, "OK button", name="OK", control_type="Button")
        ok.invoke()
        time.sleep(0.3)

    @staticmethod
    def _find_popup_item(pid: int, text: str):
        for top in uia.top_windows_of_process(pid):
            for item in top.descendants(control_type="ListItem"):
                if item.window_text() == text:
                    return item
        return None

    def _find_address_dialog(self, pid: int):
        def find():
            for top in uia.top_windows_of_process(pid):
                if uia.auto_id(top) == "Ripes__AddressDialog":
                    return top
            return None
        dlg = uia.wait_until(find, 3)
        if dlg is None:
            raise RipesError("Address dialog did not appear")
        return dlg

    def read_memory(self, address: int, words: int = 8) -> list[dict]:
        address &= ~0x3
        tab = self._in_tab("memory")
        wanted = [address + 4 * i for i in range(words)]
        got: dict[int, dict] = {}
        attempts = 0
        while len(got) < len(wanted) and attempts < 1 + words // 8:
            missing = [a for a in wanted if a not in got]
            rows = self._memory_rows(tab)
            if missing[0] not in rows:
                self._goto_address(tab, missing[0])
                tab = self._in_tab("memory")
                rows = self._memory_rows(tab)
            for a in missing:
                if a in rows:
                    got[a] = rows[a]
            attempts += 1
        out = []
        for a in wanted:
            row = got.get(a)
            value = _parse_reg(row["word"]) if row else None
            out.append({"address": f"0x{a:08x}", "word": row["word"] if row else None,
                        "bytes": row["bytes"] if row else None, "unsigned": value})
        return out

    # --------------------------------------------------------- configuration

    def select_processor(self, preset: str | None = None, xlen: int | None = None,
                         datapath: str | None = None, branch_strategy: str | None = None,
                         branch_slots: int | None = None, forwarding: bool | None = None,
                         hazard_detection: bool | None = None,
                         extensions: dict[str, bool] | None = None,
                         layout: str | None = None) -> dict:
        if preset:
            p = preset.upper()
            if p.startswith(("RV32_", "RV64_")):
                xlen = xlen or int(p[2:4])
                p = p[5:]
            if p == "5MC":  # RV64 CLI name for the two-memory multicycle
                p = "5MC_2M"
            if p not in PROCESSOR_PRESETS:
                raise ValueError(f"Unknown preset {preset!r}")
            dp, bs, slots, fw, hz = PROCESSOR_PRESETS[p]
            datapath = datapath or dp
            branch_strategy = branch_strategy or bs
            branch_slots = branch_slots if branch_slots is not None else slots
            forwarding = fw if forwarding is None else forwarding
            hazard_detection = hz if hazard_detection is None else hazard_detection

        self._stop_continuous()
        uia.post_click(self._toolbar_button(BTN_SELECT_PROCESSOR))
        dlg = self._dialog("Configure Processor")
        try:
            def combo(suffix):
                return uia.find_one(dlg, f"combo {suffix}", id_suffix=suffix, control_type="ComboBox")

            if xlen:
                self._select_combo(combo("xlen"), f"{xlen}-bit")
            if datapath:
                self._select_combo(combo("datapath"), DATAPATHS.get(datapath, datapath))
            if branch_strategy:
                self._select_combo(combo("branchStrategy"),
                                   BRANCH_STRATEGIES.get(branch_strategy, branch_strategy))
            if branch_slots is not None:
                self._select_combo(combo("branchSlots"),
                                   "" if branch_slots == 0 else f"{branch_slots}-slot")
            for suffix, wanted in (("hasForwarding", forwarding),
                                   ("hasHazardDetection", hazard_detection)):
                if wanted is not None:
                    box = uia.find_one(dlg, suffix, id_suffix=suffix)
                    if uia.is_enabled(box) and uia.toggle_state(box) != wanted:
                        uia.toggle(box)
            for ext, wanted in (extensions or {}).items():
                box = uia.find_one(dlg, f"extension {ext}", name=ext.upper(), control_type="CheckBox")
                if uia.toggle_state(box) != wanted:
                    uia.toggle(box)
            if layout:
                self._select_combo(combo("layout"), layout)
            description = uia.find_all(dlg, id_suffix="description")
            summary = {
                "xlen": uia.value_of(combo("xlen")),
                "datapath": uia.value_of(combo("datapath")),
                "branch_strategy": uia.value_of(combo("branchStrategy")),
                "branch_slots": uia.value_of(combo("branchSlots")),
                "forwarding": uia.toggle_state(uia.find_one(dlg, "fw", id_suffix="hasForwarding")),
                "hazard_detection": uia.toggle_state(
                    uia.find_one(dlg, "hz", id_suffix="hasHazardDetection")),
                "layout": uia.value_of(combo("layout")),
                "description": description[0].window_text() if description else None,
            }
            ok = uia.find_one(dlg, "OK button", name="OK", control_type="Button")
            if not uia.is_enabled(ok):
                raise RipesError(f"This combination is not a valid processor: {summary}")
            ok.invoke()
        except Exception:
            cancel = uia.find_all(dlg, name="Cancel", control_type="Button")
            if cancel:
                cancel[0].invoke()
            raise
        uia.wait_until(lambda: uia.find_window_by_title(self.window().process_id(),
                                                        "Configure Processor") is None, 5)
        time.sleep(0.8)  # the datapath view is rebuilt
        return {"selected": summary, **self.status()}

    @staticmethod
    def _select_combo(combo: uia.UIAWrapper, text: str) -> None:
        if uia.value_of(combo) == text:
            return
        try:
            combo.select(text)
        except Exception as exc:
            try:
                options = combo.texts()
            except Exception:
                options = []
            raise RipesError(f"Option {text!r} not available. Options: {options}") from exc
        time.sleep(0.2)
        try:
            combo.collapse()
        except Exception:
            pass
        if uia.value_of(combo) != text:
            raise RipesError(f"Could not select {text!r} (combo shows {uia.value_of(combo)!r})")

    def select_cache(self, cache_type: str) -> dict:
        label = CACHE_TYPES.get(cache_type, cache_type)
        self._stop_continuous()
        uia.post_click(self._toolbar_button(BTN_SELECT_CACHE))
        dlg = self._dialog("Select Cache Type")
        try:
            items = uia.find_all(dlg, name=label, control_type="TreeItem")
            if not items:
                raise RipesError(f"Cache type {label!r} not found. Options: {list(CACHE_TYPES)}")
            uia.post_click(items[0])  # tree items expose no SelectionItem pattern
            time.sleep(0.3)
            ok = uia.find_one(dlg, "OK button", name="OK", control_type="Button")
            ok.invoke()
        except Exception:
            cancel = uia.find_all(dlg, name="Cancel", control_type="Button")
            if cancel:
                cancel[0].invoke()
            raise
        time.sleep(0.5)
        return {"cache_type": label}

    # ------------------------------------------------------------------ cache

    CACHE_SPINNERS = {"ways": "ways", "sets_log2": "lines", "words_per_line_log2": "blocks"}
    CACHE_COMBOS = {"preset": "presets", "replacement_policy": "replacementPolicy",
                    "write_hit": "wrHit", "write_miss": "wrMiss"}
    CACHE_STATS = ("hits", "misses", "hitrate", "writebacks", "size")

    def _cache_levels(self, tab: uia.UIAWrapper) -> list[uia.UIAWrapper]:
        return uia.find_all(tab, control_type="TabItem")

    def _select_cache_level(self, tab: uia.UIAWrapper, level: str | None) -> str:
        levels = self._cache_levels(tab)
        if not levels:
            raise RipesError("No cache configured")
        if level is None:
            selected = [t for t in levels if t.is_selected()]
            return (selected[0] if selected else levels[0]).window_text()
        match = [t for t in levels if t.window_text().lower() == level.lower()]
        if not match:
            raise RipesError(f"Cache {level!r} not found. Options: {[t.window_text() for t in levels]}")
        if not match[0].is_selected():
            match[0].select()
            time.sleep(0.4)
        return match[0].window_text()

    def _read_cache_panel(self, tab: uia.UIAWrapper) -> dict:
        def by_suffix(suffix):
            found = uia.find_all(tab, id_suffix="." + suffix)
            return uia.value_of(found[0]) if found else None
        config = {k: by_suffix(v) for k, v in {**self.CACHE_COMBOS, **self.CACHE_SPINNERS}.items()}
        stats = {k: by_suffix(k) for k in self.CACHE_STATS}
        return {"config": config, "stats": stats}

    def cache_info(self) -> list[dict]:
        """Configuration and statistics of every cache shown in the Cache tab."""
        tab = self._in_tab("cache")
        names = [t.window_text() for t in self._cache_levels(tab)]
        current = self._select_cache_level(tab, None) if names else None
        out = []
        for name in names:
            self._select_cache_level(tab, name)
            tab = self._in_tab("cache")
            out.append({"cache": name, **self._read_cache_panel(tab)})
        if current:
            self._select_cache_level(self._in_tab("cache"), current)
        return out

    def configure_cache(self, level: str | None = None, preset: str | None = None,
                        ways: int | None = None, sets_log2: int | None = None,
                        words_per_line_log2: int | None = None,
                        replacement_policy: str | None = None, write_hit: str | None = None,
                        write_miss: str | None = None) -> dict:
        tab = self._in_tab("cache")
        name = self._select_cache_level(tab, level)
        tab = self._in_tab("cache")
        combos = {"preset": preset, "replacement_policy": replacement_policy,
                  "write_hit": write_hit, "write_miss": write_miss}
        for key, text in combos.items():
            if text is not None:
                combo = uia.find_one(tab, key, id_suffix="." + self.CACHE_COMBOS[key],
                                     control_type="ComboBox")
                self._select_combo(combo, text)
        spins = {"ways": ways, "sets_log2": sets_log2, "words_per_line_log2": words_per_line_log2}
        for key, value in spins.items():
            if value is not None:
                spin = uia.find_one(tab, key, id_suffix="." + self.CACHE_SPINNERS[key],
                                    control_type="Spinner")
                rv = spin.iface_range_value
                if not rv.CurrentMinimum <= value <= rv.CurrentMaximum:
                    raise RipesError(f"{key} must be in [{rv.CurrentMinimum:g}, {rv.CurrentMaximum:g}]")
                rv.SetValue(float(value))
                time.sleep(0.2)
        return {"cache": name, **self._read_cache_panel(self._in_tab("cache"))}

    # ------------------------------------------------------------------ files

    def load_file(self, path: str) -> dict:
        code = Path(path).read_text(encoding="utf-8")
        result = self.set_source(code)
        result["loaded_from"] = str(Path(path).resolve())
        return result

    def save_source(self, path: str) -> str:
        target = Path(path)
        target.write_text(self.get_source(), encoding="utf-8")
        return str(target.resolve())
