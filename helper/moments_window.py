import win32api
import win32con
import win32gui
import win32process


def _window_pid(hwnd: int) -> int:
    try:
        return int(win32process.GetWindowThreadProcessId(hwnd)[1])
    except Exception:
        return 0


def find_window_by_class_pid(class_name: str, title: str, target_pid: int | None = None) -> int:
    """按窗口类名、标题和可选 PID 定位窗口；多开时不以第一个匹配项代替。"""
    found = []

    def visit(hwnd, _param):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.GetWindowText(hwnd) != title:
            return True
        if win32gui.GetClassName(hwnd) != class_name:
            return True
        pid = _window_pid(hwnd)
        if target_pid is not None and pid != int(target_pid):
            return True
        found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    if len(found) == 1:
        return found[0]
    return 0


def find_moments_window(target_pid: int | None = None) -> int:
    """定位指定微信进程的朋友圈窗口；未指定 PID 时仅接受唯一匹配窗口。"""
    found = []

    def visit(hwnd, _param):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.GetWindowText(hwnd) != "朋友圈":
            return True
        class_name = win32gui.GetClassName(hwnd)
        if not (class_name.startswith("Qt") or class_name == "SnsWnd"):
            return True
        pid = _window_pid(hwnd)
        if target_pid is not None and pid != int(target_pid):
            return True
        found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    if len(found) == 1:
        return found[0]
    return 0


def scroll_moments(hwnd: int, notches: int = 10) -> None:
    """向指定朋友圈窗口发送滚轮事件。"""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    x = (left + right) // 2
    y = (top + bottom) // 2
    delta = win32api.MAKELONG(0, -120 * notches)
    point = win32api.MAKELONG(x, y)
    if win32gui.GetClassName(hwnd).startswith("Qt"):
        win32api.PostMessage(hwnd, win32con.WM_MOUSEWHEEL, delta, point)
        return
    win32api.SendMessage(hwnd, win32con.WM_MOUSEWHEEL, delta, point)
