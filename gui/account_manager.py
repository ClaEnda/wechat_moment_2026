from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from helper.account_profiles import AccountProfileError, AccountProfileStore
from helper.account_discovery import (
    discover_account_directories,
    discover_running_wechat_processes,
)
from helper.account_profiles import profile_cache_dir


def choose_account_profile(parent=None):
    """
    显示本机账号档案选择器。
    进程列表和数据目录只作为候选信息；账号、目录及密钥由用户确认。
    返回 (account_info, secrets)，取消时返回 None。
    """
    store = AccountProfileStore()
    profiles = store.list_profiles()
    processes = discover_running_wechat_processes()
    candidates = discover_account_directories()

    owns_root = parent is None
    root = tk.Tk() if owns_root else tk.Toplevel(parent)
    root.title("微信多账号管理")
    root.geometry("980x650")
    root.minsize(860, 560)
    root.transient(parent if parent is not None else None)
    root.grab_set()

    selected = {"value": None}
    profile_tree = ttk.Treeview(
        root,
        columns=("wxid", "name", "version", "folder"),
        show="headings",
        height=9,
    )
    for col, title, width in [
        ("wxid", "微信 ID", 190),
        ("name", "显示名称", 170),
        ("version", "版本", 90),
        ("folder", "绑定的数据目录", 470),
    ]:
        profile_tree.heading(col, text=title)
        profile_tree.column(col, width=width, anchor="w")
    profile_tree.pack(fill="x", padx=12, pady=(12, 5))

    process_text = "同时运行的微信进程："
    if processes:
        process_text += "、".join(f"{item.image_name} PID {item.pid}" for item in processes)
    else:
        process_text += "未发现（仍可手动添加已经存在的数据目录）"
    ttk.Label(root, text=process_text, wraplength=940).pack(anchor="w", padx=14, pady=3)

    ttk.Label(root, text="自动发现的数据目录候选项（需要手动确认账号映射）").pack(
        anchor="w", padx=14, pady=(8, 3)
    )
    candidate_tree = ttk.Treeview(
        root,
        columns=("guess", "account", "storage"),
        show="headings",
        height=7,
    )
    for col, title, width in [
        ("guess", "目录名 / wxid 猜测", 180),
        ("account", "账号数据目录", 370),
        ("storage", "数据库目录", 370),
    ]:
        candidate_tree.heading(col, text=title)
        candidate_tree.column(col, width=width, anchor="w")
    candidate_tree.pack(fill="both", expand=True, padx=12, pady=4)

    candidate_map = {}
    for idx, item in enumerate(candidates):
        candidate_map[str(idx)] = item
        candidate_tree.insert(
            "", "end", iid=str(idx),
            values=(item.wxid_guess or item.folder_name, item.account_dir, item.db_storage),
        )

    def refresh_profiles():
        for item in profile_tree.get_children():
            profile_tree.delete(item)
        for p in store.list_profiles():
            profile_tree.insert(
                "", "end", iid=p["wxid"],
                values=(
                    p["wxid"],
                    p["display_name"],
                    p["wechat_version"],
                    p["account_dir"],
                ),
            )

    refresh_profiles()

    def open_profile_editor(existing=None):
        selected_candidate = candidate_tree.selection()
        candidate = candidate_map.get(selected_candidate[0]) if selected_candidate else None

        win = tk.Toplevel(root)
        win.title("添加 / 编辑微信账号档案")
        win.geometry("760x650")
        win.transient(root)
        win.grab_set()

        variables = {
            "wxid": tk.StringVar(value=(existing or {}).get("wxid") or (candidate.wxid_guess if candidate else "")),
            "display_name": tk.StringVar(value=(existing or {}).get("display_name", "")),
            "wechat_version": tk.StringVar(value=(existing or {}).get("wechat_version", "4.x")),
            "account_dir": tk.StringVar(value=(existing or {}).get("account_dir") or (candidate.account_dir if candidate else "")),
            "db_storage": tk.StringVar(value=(existing or {}).get("db_storage") or (candidate.db_storage if candidate else "")),
            "process_ids": tk.StringVar(value=",".join(str(x) for x in (existing or {}).get("process_ids", []))),
        }

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        def row(label, variable, index, browse=False, directory=True):
            ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", pady=5, padx=(0, 10))
            entry = ttk.Entry(frame, textvariable=variable, width=70)
            entry.grid(row=index, column=1, sticky="ew", pady=5)
            if browse:
                def pick():
                    chosen = filedialog.askdirectory(parent=win, title=f"选择{label}")
                    if chosen:
                        variable.set(chosen)
                ttk.Button(frame, text="浏览…", command=pick).grid(row=index, column=2, padx=(8, 0))
            return entry

        row("微信 wxid", variables["wxid"], 0)
        row("微信显示名称", variables["display_name"], 1)
        ttk.Label(frame, text="微信版本").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 10))
        version_box = ttk.Combobox(
            frame, textvariable=variables["wechat_version"],
            values=("4.x", "3.x"), state="readonly", width=12,
        )
        version_box.grid(row=2, column=1, sticky="w", pady=5)
        row("账号数据目录", variables["account_dir"], 3, browse=True)
        row("db_storage（4.x）", variables["db_storage"], 4, browse=True)
        row("对应此账号的微信主进程 PID（单个）", variables["process_ids"], 5)

        ttk.Separator(frame).grid(row=6, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Label(
            frame,
            text="密钥仅在本机输入并通过 Windows DPAPI 加密保存。不会写入明文 JSON。",
            foreground="#1f6b3b",
            wraplength=700,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 6))

        secret_vars = {
            "legacy_db_key": tk.StringVar(),
            "sns_db_key": tk.StringVar(),
            "contact_db_key": tk.StringVar(),
            "image_key": tk.StringVar(),
        }
        secret_labels = [
            ("3.x 数据库密钥", "legacy_db_key"),
            ("4.x 朋友圈数据库密钥（64 位十六进制）", "sns_db_key"),
            ("4.x 联系人数据库密钥（64 位十六进制）", "contact_db_key"),
            ("图片 / CDN 密钥（可选，当前版本仅安全保存）", "image_key"),
        ]
        for offset, (label, key) in enumerate(secret_labels, start=8):
            ttk.Label(frame, text=label).grid(row=offset, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Entry(frame, textvariable=secret_vars[key], show="•", width=70).grid(
                row=offset, column=1, columnspan=2, sticky="ew", pady=5
            )

        ttk.Label(
            frame,
            text="说明：自动发现仅用于列出进程和目录。若目录与微信账号无法准确对应，请手动选择目录并填写 wxid。"
        ).grid(row=12, column=0, columnspan=3, sticky="w", pady=(8, 12))

        def save():
            profile = {key: var.get().strip() for key, var in variables.items()}
            pid_text = variables["process_ids"].get().strip()
            if "," in pid_text or ";" in pid_text:
                messagebox.showerror("PID 格式错误", "一个账号档案只绑定一个主进程 PID，请为其他微信实例分别建立档案。", parent=win)
                return
            profile["process_ids"] = [pid_text] if pid_text else []
            version = profile["wechat_version"]
            secrets = {key: var.get().strip() for key, var in secret_vars.items() if var.get().strip()}
            if version == "4.x":
                if not secrets.get("sns_db_key") or not secrets.get("contact_db_key"):
                    messagebox.showerror("缺少密钥", "4.x 账号需要分别填写朋友圈数据库密钥和联系人数据库密钥。", parent=win)
                    return
                for field in ("sns_db_key", "contact_db_key"):
                    value = secrets[field].replace(" ", "")
                    if len(value) != 64:
                        messagebox.showerror("密钥格式错误", f"{field} 必须是 64 位十六进制密钥。", parent=win)
                        return
                    try:
                        bytes.fromhex(value)
                    except ValueError:
                        messagebox.showerror("密钥格式错误", f"{field} 必须是十六进制字符。", parent=win)
                        return
                    secrets[field] = value
            else:
                if not secrets.get("legacy_db_key"):
                    messagebox.showerror("缺少密钥", "3.x 账号需要填写该账号的数据库密钥。", parent=win)
                    return
            try:
                store.save_profile(profile, secrets)
            except (AccountProfileError, OSError) as exc:
                messagebox.showerror("保存失败", str(exc), parent=win)
                return
            refresh_profiles()
            win.destroy()

        button_bar = ttk.Frame(frame)
        button_bar.grid(row=13, column=0, columnspan=3, sticky="e")
        ttk.Button(button_bar, text="取消", command=win.destroy).pack(side="right", padx=5)
        ttk.Button(button_bar, text="保存档案", command=save).pack(side="right", padx=5)

    def add_profile():
        open_profile_editor()

    def edit_profile():
        selection = profile_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个账号档案。", parent=root)
            return
        open_profile_editor(store.get_profile(selection[0]))

    def remove_profile():
        selection = profile_tree.selection()
        if not selection:
            return
        wxid = selection[0]
        if messagebox.askyesno("删除档案", f"删除 {wxid} 的本地账号档案？不会删除微信原始数据目录。", parent=root):
            store.remove_profile(wxid)
            refresh_profiles()

    def use_profile():
        selection = profile_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先添加或选择一个账号档案。", parent=root)
            return
        wxid = selection[0]
        try:
            profile = store.get_profile(wxid)
            secrets = store.get_secrets(wxid)
            required = ("sns_db_key", "contact_db_key") if profile["wechat_version"] == "4.x" else ("legacy_db_key",)
            missing = [name for name in required if not secrets.get(name)]
            if missing:
                raise AccountProfileError("该账号缺少密钥，请编辑档案并补充。")
            cache_dir = profile_cache_dir(wxid)
            account_info = {
                "weixin4": profile["wechat_version"] == "4.x",
                "filePath": profile["account_dir"],
                "dbStorage": profile.get("db_storage") or "",
                "wxid": wxid,
                "display_name": profile["display_name"],
                "profileCacheDir": cache_dir,
                "databaseDir": os.path.join(cache_dir, "database"),
                "mediaCacheDir": os.path.join(cache_dir, "media_cache"),
                "manual_keys": secrets,
                "key": secrets.get("legacy_db_key", ""),
                "process_ids": profile.get("process_ids", []),
                "process_id": (profile.get("process_ids") or [None])[0],
            }
        except (AccountProfileError, OSError) as exc:
            messagebox.showerror("账号无法使用", str(exc), parent=root)
            return
        selected["value"] = account_info
        root.destroy()

    button_bar = ttk.Frame(root)
    button_bar.pack(fill="x", padx=12, pady=12)
    ttk.Button(button_bar, text="添加账号 / 手动匹配", command=add_profile).pack(side="left", padx=4)
    ttk.Button(button_bar, text="编辑账号 / 密钥", command=edit_profile).pack(side="left", padx=4)
    ttk.Button(button_bar, text="删除档案", command=remove_profile).pack(side="left", padx=4)
    ttk.Button(button_bar, text="使用选中账号", command=use_profile).pack(side="right", padx=4)
    ttk.Button(button_bar, text="退出", command=root.destroy).pack(side="right", padx=4)

    if profiles:
        profile_tree.selection_set(profiles[0]["wxid"])
    root.mainloop()
    return selected["value"]
