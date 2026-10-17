import os
import threading
import traceback
from time import sleep


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    from gui.gui import Gui
    from decrypter.weixin4 import probe_client

    gui = Gui()
    gui_thread = threading.Thread(target=gui.run_gui)
    gui_thread.start()

    while gui.waiting_label is None:
        sleep(0.05)

    probe = probe_client()
    if probe.get("state") == "weixin4":
        gui.waiting_label.config(text="微信 4.1 已登录")
        gui.wechat_logged_in(probe["account"])
        return
    if probe.get("state") == "weixin4-error":
        gui.waiting_label.config(text=probe.get("message") or "微信 4.1 暂不可用")
        return

    from pywxdump import read_info

    info = ""
    while True:
        try:
            info = read_info(None, is_logging=False)
        except Exception:
            traceback.print_exc()
            info = ""
        if gui.waiting_label is None:
            sleep(0.05)
            continue
        if isinstance(info, str) or not info:
            gui.waiting_label.config(text="请启动微信....")
            sleep(0.5)
        elif isinstance(info, list) and info[0].get("key") == "None":
            gui.waiting_label.config(text="请登陆微信....")
            sleep(0.5)
        else:
            break

    gui.wechat_logged_in(info[0])


if __name__ == "__main__":
    main()
