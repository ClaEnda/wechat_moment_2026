import os
import threading
from time import sleep


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # 多开场景下由用户选择已保存的账号档案，避免默认绑定到“第一个”微信目录。
    from gui.account_manager import choose_account_profile
    account_info = choose_account_profile()
    if not account_info:
        return

    from gui.gui import Gui

    gui = Gui()
    gui_thread = threading.Thread(target=gui.run_gui, daemon=True)
    gui_thread.start()

    while gui.waiting_label is None:
        sleep(0.05)

    gui.wechat_logged_in(account_info)


if __name__ == "__main__":
    main()
