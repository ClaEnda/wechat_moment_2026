import win32api
import win32con
import win32gui


def find_moments_window() -> int:
    """定位当前打开的朋友圈窗口。微信 4 的类名以 Qt 开头，旧版是 SnsWnd。"""
    found = []

    def visit(hwnd, _param):
        if (
            win32gui.IsWindowVisible(hwnd)
            and win32gui.GetWindowText(hwnd) == "朋友圈"
            and win32gui.GetClassName(hwnd).startswith("Qt")
        ):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    if found:
        return found[0]
    return win32gui.FindWindow("SnsWnd", "朋友圈") or 0


def scroll_moments(hwnd: int, notches: int = 10) -> None:
    """向朋友圈窗口发送向下的滚轮，让微信继续加载更早的动态。"""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    x = (left + right) // 2
    y = (top + bottom) // 2
    delta = win32api.MAKELONG(0, -120 * notches)
    point = win32api.MAKELONG(x, y)
    if win32gui.GetClassName(hwnd).startswith("Qt"):
        win32api.PostMessage(hwnd, win32con.WM_MOUSEWHEEL, delta, point)
        return
    win32api.SendMessage(hwnd, win32con.WM_MOUSEWHEEL, delta, point)
