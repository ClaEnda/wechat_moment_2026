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
        gui.wechat_logged_in(probe)
        return
    if probe.get("state") == "weixin4-error":
        gui.wechat_logged_in({
            "accounts": [],
            "process_ids": probe.get("process_ids") or [],
            "message": probe.get("message") or "已发现微信，但未自动找到数据目录",
        })
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
        elif isinstance(info, list) and not any(item.get("key") not in (None, "", "None") for item in info if isinstance(item, dict)):
            gui.waiting_label.config(text="请登陆微信....")
            sleep(0.5)
        else:
            break

    legacy_accounts = []
    for item in info:
        if not isinstance(item, dict) or item.get("key") in (None, "", "None"):
            continue
        account = dict(item)
        account["weixin4"] = False
        account.setdefault("account_dir", account.get("filePath") or account.get("db_path") or "")
        account.setdefault("wxid", account.get("wxid") or "")
        account.setdefault("displayName", account.get("nickname") or account.get("wxid") or "")
        legacy_accounts.append(account)
    gui.wechat_logged_in({"accounts": legacy_accounts, "process_ids": []})


if __name__ == "__main__":
    main()
