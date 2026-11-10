from __future__ import annotations

import csv
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class RunningWechatProcess:
    pid: int
    image_name: str
    memory_kb: int


@dataclass(frozen=True)
class AccountDirectoryCandidate:
    account_dir: str
    db_storage: str
    folder_name: str
    wxid_guess: str


def discover_running_wechat_processes() -> list[RunningWechatProcess]:
    """仅枚举运行中的微信进程及 PID，不读取进程内存或进程凭据。"""
    if os.name != "nt":
        return []
    names = {"weixin.exe", "wechat.exe"}
    result = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    found = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 5 or row[0].strip().lower() not in names:
            continue
        try:
            pid = int(row[1].strip())
        except ValueError:
            continue
        mem = row[4].replace(",", "").replace("K", "").replace(" ", "")
        try:
            memory_kb = int(mem)
        except ValueError:
            memory_kb = 0
        found.append(RunningWechatProcess(pid, row[0], memory_kb))
    return sorted(found, key=lambda item: item.pid)


def discover_account_directories() -> list[AccountDirectoryCandidate]:
    """
    自动枚举本机微信数据目录候选项。该列表不代表 PID 与账号的确定绑定，
    最终映射必须由用户确认或手动选择。
    """
    try:
        from decrypter.weixin4 import _iter_accounts
        accounts = _iter_accounts()
    except Exception:
        accounts = []

    result = []
    seen = set()
    for account_dir, db_storage in accounts:
        account_dir = os.path.abspath(account_dir)
        db_storage = os.path.abspath(db_storage)
        if account_dir in seen:
            continue
        seen.add(account_dir)
        folder_name = os.path.basename(account_dir.rstrip("\\/"))
        wxid_guess = folder_name if folder_name.lower().startswith("wxid_") else ""
        result.append(AccountDirectoryCandidate(
            account_dir=account_dir,
            db_storage=db_storage,
            folder_name=folder_name,
            wxid_guess=wxid_guess,
        ))
    return result
