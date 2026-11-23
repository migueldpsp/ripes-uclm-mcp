"""Low-level Windows UI Automation (UIA) helpers used to drive Ripes.

Everything here works on the stock, unmodified Ripes binary: Qt 6 exposes its
widgets through UIA, using the Qt object names as AutomationIds (for example
``Ripes__MainWindow.centralwidget.tabbar``).

Two rules learned the hard way:

* Never use the UIA *Invoke* pattern on a control that opens a modal dialog.
  Qt runs the dialog's event loop inside the UIA callback and the dialog's
  contents never become accessible. For those controls we post real mouse
  messages to the window instead (``post_click``), which also leaves the
  user's mouse cursor alone.
* Widgets on hidden tabs are not part of the UIA tree, so callers must show
  the right tab before looking for them.

This module must only be imported from the dedicated UI thread (see
``server.py``), because pywinauto creates its COM objects on import.
"""

from __future__ import annotations

import ctypes
import io
import time
from typing import Callable, Iterable

import win32api
import win32con
import win32gui
import win32ui
from pywinauto import Desktop
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo

MAIN_WINDOW_ID = "Ripes__MainWindow"


class RipesError(RuntimeError):
    """Raised when Ripes is not in a state that allows the requested action."""


def desktop() -> Desktop:
    return Desktop(backend="uia")


def top_windows_of_process(pid: int) -> list[UIAWrapper]:
    return [w for w in desktop().windows() if w.process_id() == pid]


def find_main_window() -> UIAWrapper | None:
    wins = desktop().windows(auto_id=MAIN_WINDOW_ID)
    return wins[0] if wins else None


def find_window_by_title(pid: int, title: str) -> UIAWrapper | None:
    for w in top_windows_of_process(pid):
        if w.window_text() == title:
            return w
    return None


def wait_until(predicate: Callable[[], object], timeout: float, interval: float = 0.05):
    """Poll ``predicate`` until it returns a truthy value or ``timeout`` expires."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = predicate()
        except Exception:  # UIA elements can vanish while Qt rebuilds widgets
            value = None
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


# --------------------------------------------------------------------------
# Element lookup
# --------------------------------------------------------------------------

def auto_id(elem: UIAWrapper) -> str:
    return elem.element_info.automation_id or ""


def find_all(root: UIAWrapper, *, id_suffix: str | None = None, id_contains: str | None = None,
             name: str | None = None, control_type: str | None = None,
             class_name: str | None = None) -> list[UIAWrapper]:
    kwargs = {"control_type": control_type} if control_type else {}
    # Walk element infos and only wrap the matches: while Ripes is running,
    # widgets can disappear mid-walk and wrapping a dead element raises.
    for attempt in range(3):
        try:
            infos = root.element_info.descendants(**kwargs)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.1)
    out = []
    for info in infos:
        try:
            aid = info.automation_id or ""
            info_name, info_class = info.name, info.class_name
        except Exception:
            continue
        if id_suffix is not None and not aid.endswith(id_suffix):
            continue
        if id_contains is not None and id_contains not in aid:
            continue
        if name is not None and info_name != name:
            continue
        if class_name is not None and info_class != class_name:
            continue
        try:
            out.append(UIAWrapper(info))
        except Exception:
            continue
    return out


def find_one(root: UIAWrapper, what: str = "control", **criteria) -> UIAWrapper:
    found = find_all(root, **criteria)
    if not found:
        raise RipesError(f"Could not find {what} ({criteria}). Is the right tab visible?")
    return found[0]


def wrap(raw_element) -> UIAWrapper:
    """Wrap a raw IUIAutomationElement (e.g. a grid cell) in a pywinauto wrapper."""
    return UIAWrapper(UIAElementInfo(raw_element))


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def text_of(elem: UIAWrapper) -> str:
    """Full text of an edit/text control (TextPattern first, ValuePattern second)."""
    try:
        return elem.iface_text.DocumentRange.GetText(-1)
    except Exception:
        pass
    try:
        return elem.iface_value.CurrentValue
    except Exception:
        return elem.window_text()


def value_of(elem: UIAWrapper) -> str:
    try:
        return elem.iface_value.CurrentValue
    except Exception:
        return elem.window_text()


def toggle_state(elem: UIAWrapper) -> bool:
    return bool(elem.iface_toggle.CurrentToggleState)


def is_enabled(elem: UIAWrapper) -> bool:
    return bool(elem.element_info.enabled)


def read_grid(table: UIAWrapper, columns: Iterable[int] | None = None) -> list[list[str]]:
    """Read every row of a QTableView through the UIA Grid pattern.

    Unlike walking the children, GridPattern.GetItem also returns rows that are
    scrolled out of view.
    """
    grid = table.iface_grid
    n_rows, n_cols = grid.CurrentRowCount, grid.CurrentColumnCount
    cols = list(columns) if columns is not None else list(range(n_cols))
    return [[grid.GetItem(r, c).CurrentName for c in cols] for r in range(n_rows)]


def grid_cell(table: UIAWrapper, row: int, col: int) -> UIAWrapper:
    return wrap(table.iface_grid.GetItem(row, col))


# --------------------------------------------------------------------------
# Input without touching the user's mouse
# --------------------------------------------------------------------------

def top_level_hwnd(elem: UIAWrapper) -> int:
    top = elem.top_level_parent()
    hwnd = top.handle
    if not hwnd:
        raise RipesError("Element has no native top-level window")
    return hwnd


def restore_window(hwnd: int) -> None:
    """Un-minimise a window; posted mouse messages need real client coordinates."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)


def post_click_at(hwnd: int, x: int, y: int, double: bool = False) -> None:
    """Post a left click at screen coordinates (x, y) to ``hwnd``."""
    restore_window(hwnd)
    cx, cy = win32gui.ScreenToClient(hwnd, (x, y))
    lparam = win32api.MAKELONG(cx & 0xFFFF, cy & 0xFFFF)
    win32api.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    if double:
        win32api.PostMessage(hwnd, win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON, lparam)
        win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)


def post_click(elem: UIAWrapper, double: bool = False) -> None:
    """Post a click to the centre of ``elem``."""
    hwnd = top_level_hwnd(elem)
    restore_window(hwnd)
    r = elem.rectangle()
    post_click_at(hwnd, (r.left + r.right) // 2, (r.top + r.bottom) // 2, double)


def post_wheel(elem: UIAWrapper, notches: int) -> None:
    """Scroll the widget under ``elem`` (positive = up). Qt scrolls 3 rows per notch."""
    hwnd = top_level_hwnd(elem)
    r = elem.rectangle()
    x, y = (r.left + r.right) // 2, (r.top + r.bottom) // 2
    delta = (120 * notches) & 0xFFFF
    win32api.PostMessage(hwnd, win32con.WM_MOUSEWHEEL, win32api.MAKELONG(0, delta),
                         win32api.MAKELONG(x & 0xFFFF, y & 0xFFFF))


def ensure_cell_visible(table: UIAWrapper, row: int, col: int, header_bottom: int) -> UIAWrapper:
    """Scroll ``table`` with posted wheel events until the cell is fully visible."""
    view = table.rectangle()
    for _ in range(200):
        cell = grid_cell(table, row, col)
        r = cell.rectangle()
        if r.top < header_bottom:
            post_wheel(table, 1)
        elif r.bottom > view.bottom - 2:
            post_wheel(table, -1)
        else:
            return cell
        time.sleep(0.08)
    raise RipesError(f"Could not scroll row {row} into view")


def post_key(hwnd: int, vk: int) -> None:
    win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
    win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0xC0000000)


# --------------------------------------------------------------------------
# Screenshots
# --------------------------------------------------------------------------

PW_RENDERFULLCONTENT = 0x00000002


def capture_window_png(hwnd: int, max_width: int = 1600) -> bytes:
    """Capture a window as PNG (works even if other windows cover it)."""
    from PIL import Image

    img = capture_window(hwnd)
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def is_checkbox_checked(hwnd: int, rect) -> bool:
    """Tell whether the checkbox drawn inside screen ``rect`` is ticked.

    Qt does not report the check state of the instruction-memory breakpoint
    cells through UIA (the model returns a bool, not a Qt::CheckState), so we
    look at the pixels: a ticked box is filled with the Windows accent colour,
    an empty one is white with a grey border.
    """
    img = capture_window(hwnd)
    left, top, _, _ = win32gui.GetWindowRect(hwnd)
    crop = img.crop((rect.left - left, rect.top - top, rect.right - left, rect.bottom - top))
    # Accent-blue pixels (the default Windows 11 accent is around (0, 95, 184)).
    blue = sum(1 for r, g, b in crop.getdata() if b > 140 and b - r > 90 and b - g > 30)
    return blue > 12


def capture_window(hwnd: int):
    """Capture a window into a PIL image with PrintWindow."""
    from PIL import Image

    restore_window(hwnd)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    mem_dc = src_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(src_dc, width, height)
    mem_dc.SelectObject(bitmap)
    try:
        ctypes.windll.user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        info = bitmap.GetInfo()
        raw = bitmap.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), raw, "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        mem_dc.DeleteDC()
        src_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
    return img


def toggle(elem: UIAWrapper) -> None:
    """Flip a checkable control through the UIA Toggle pattern."""
    elem.iface_toggle.Toggle()
