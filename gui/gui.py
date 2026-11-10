import os
import re
import sys
import subprocess
import tkinter
from tkinter import filedialog, messagebox, simpledialog
import tkinter.font
import tkinter.ttk
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import tkcalendar
from decrypter.db_decrypt import DatabaseDecrypter
from decrypter.image_decrypt import ImageDecrypter
from decrypter.video_decrypt import VideoDecrypter
from gui.auto_scroll_guide import AutoScrollGuide
from gui.tool_tip import ToolTip
from entity.contact import Contact
from exporter.html_exporter import HtmlExporter
from gui.listbox_with_search import ListboxWithSearch
from account_profiles import AccountProfileStore


class Gui:
    def __init__(self):

        self.restart_note1 = None
        self.restart_note2 = None
        self.auto_scroll_guide = None
        self.convert_video = None
        self.convert_video_var = None
        self.html_exporter_thread = None
        self.confirm_button_text = None
        self.succeed_label_2 = None
        self.succeed_label = None
        self.auto_scroll_button_text = None
        self.warning_label = None
        self.root = None
        self.waiting_label = None
        self.listbox = None
        self.begin_calendar = None
        self.end_calendar = None
        self.end_calendar_label = None
        self.begin_calendar_label = None
        self.confirm_button = None
        self.decrypt_progressbar = None
        self.export_progressbar = None
        self.next_step_button = None
        self.decrypter = None
        self.auto_scroll_button = None
        self.auto_scrolling_thread = None
        self.decrypt_note = None
        self.decrypt_note_text = None
        self.account_info = None
        self.account_profiles = []
        self.available_process_ids = []
        self.account_profile_store = AccountProfileStore()
        self.account_combo = None
        self.account_combo_var = None
        self.account_picker_frame = None
        self.video_decrypter = None
        self.image_decrypter = None
        self.export_dir_name = None
        self.exporting = False
        self.step_labels = []
        self.step_help = None
        self.export_panel = None
        # 1: 自动滚动数据 2: 解密数据库 3: 导出
        self.page_stage = 1

    def _setup_style(self):
        style = tkinter.ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("微软雅黑", 10), background="#f7f8fa")
        style.configure("TLabel", background="#f7f8fa", foreground="#1f2937")
        style.configure("TFrame", background="#f7f8fa")
        style.configure("TButton", font=("微软雅黑", 10), padding=6)
        style.configure(
            "Primary.TButton",
            font=("微软雅黑", 10),
            padding=8,
            background="#2563eb",
            foreground="#ffffff",
        )
        style.map(
            "Primary.TButton",
            background=[("pressed", "#1d4ed8"), ("active", "#3b82f6"), ("disabled", "#cbd5e1")],
            foreground=[("disabled", "#f8fafc")],
        )

    def _show_step(self, current):
        for index, label in enumerate(self.step_labels, start=1):
            if index == current:
                label.config(bg="#2563eb", fg="#ffffff")
            else:
                label.config(bg="#e8edf5", fg="#5c6b80")

    def run_gui(self):
        self.root = tkinter.Tk()
        self.root.geometry('760x780')
        self.root.title('朋友圈导出')
        self.root.configure(bg="#f7f8fa")
        self._setup_style()

        step_bar = tkinter.Frame(self.root, bg="#f7f8fa")
        for name in ("1 加载朋友圈", "2 复制到本机", "3 选择并导出"):
            label = tkinter.Label(
                step_bar,
                text=name,
                font=("微软雅黑", 10),
                bg="#e8edf5",
                fg="#5c6b80",
                padx=14,
                pady=5,
            )
            label.pack(side="left", padx=4)
            self.step_labels.append(label)
        step_bar.place(relx=0.5, rely=0.04, anchor="center")
        self._show_step(1)

        self.waiting_label = tkinter.ttk.Label(self.root, text="正在连接微信....",
                                               font=("微软雅黑", 16), anchor='center')
        self.waiting_label.place(relx=0.5, rely=0.11, anchor='center')

        self.root.mainloop()

    def wechat_logged_in(self, account_info):
        """兼容单账号入口；微信 4.x 多实例会进入账号选择器。"""
        if isinstance(account_info, dict) and isinstance(account_info.get("accounts"), list):
            self.available_process_ids = account_info.get("process_ids") or []
            discovered = account_info.get("accounts") or []
            saved = self.account_profile_store.load_profiles()
            by_path = {
                os.path.normcase(os.path.abspath(p.get("account_dir", ""))): p
                for p in saved
            }
            merged = []
            seen = set()
            for item in discovered:
                profile = dict(item)
                path = os.path.normcase(os.path.abspath(profile.get("account_dir") or profile.get("filePath") or ""))
                previous = by_path.get(path, {})
                profile["profile_id"] = profile.get("profile_id") or previous.get("profile_id") or self.account_profile_store.profile_id_for_path(path)
                profile["wxid"] = profile.get("wxid") or previous.get("wxid") or ""
                profile["display_name"] = profile.get("displayName") or previous.get("display_name") or profile.get("wxid") or os.path.basename(path)
                profile["displayName"] = profile["display_name"]
                profile["weixin4"] = bool(profile.get("weixin4", True))
                if path not in seen:
                    merged.append(profile)
                    seen.add(path)
                    self.account_profile_store.save_profile(profile)
            for previous in saved:
                path = os.path.normcase(os.path.abspath(previous.get("account_dir", "")))
                if path and path not in seen and os.path.isdir(path):
                    profile = dict(previous)
                    profile.update({
                        "filePath": previous.get("account_dir"),
                        "dbStorage": previous.get("db_storage"),
                        "displayName": previous.get("display_name") or previous.get("wxid") or os.path.basename(path),
                        "weixin4": bool(previous.get("weixin4", True)),
                        "availableProcessIds": self.available_process_ids,
                        "process_ids": previous.get("process_ids") or self.available_process_ids,
                    })
                    merged.append(profile)
                    seen.add(path)
            self.account_profiles = merged
            self._render_account_picker()
            return

        self.available_process_ids = account_info.get("availableProcessIds") or account_info.get("process_ids") or []
        self.account_profiles = [dict(account_info)]
        self._activate_account(account_info)

    def _render_account_picker(self):
        if self.account_picker_frame:
            self.account_picker_frame.destroy()
        self.account_picker_frame = tkinter.Frame(self.root, bg="#f7f8fa")
        self.account_picker_frame.place(relx=0.5, rely=0.43, anchor="center")
        count = len(self.account_profiles)
        status = (self.account_info or {}).get("message") or ""
        self.waiting_label.config(
            text=f"{status}  检测到 {count} 个账号数据目录，运行中的微信进程：{len(self.available_process_ids)} 个"
        )
        tkinter.Label(
            self.account_picker_frame,
            text="选择要处理的微信账号。每个账号的数据副本、媒体缓存和导出目录彼此隔离。",
            font=("微软雅黑", 10), bg="#f7f8fa", fg="#334155", wraplength=650,
        ).pack(pady=(0, 12))

        labels = []
        for profile in self.account_profiles:
            name = profile.get("displayName") or profile.get("wxid") or os.path.basename(profile.get("account_dir", ""))
            wxid = profile.get("wxid") or "wxid 待识别"
            folder = os.path.basename(profile.get("account_dir") or "")
            labels.append(f"{name}  |  {wxid}  |  {folder}")
        self.account_combo_var = tkinter.StringVar()
        self.account_combo = tkinter.ttk.Combobox(
            self.account_picker_frame, textvariable=self.account_combo_var,
            values=labels, state="readonly", width=72,
        )
        self.account_combo.pack(pady=5)
        if labels:
            self.account_combo.current(0)

        buttons = tkinter.Frame(self.account_picker_frame, bg="#f7f8fa")
        buttons.pack(pady=10)
        tkinter.ttk.Button(
            buttons, text="使用所选账号", command=self._use_selected_account, style="Primary.TButton"
        ).pack(side="left", padx=5)
        tkinter.ttk.Button(
            buttons, text="添加/手动匹配数据目录", command=self._add_account_directory
        ).pack(side="left", padx=5)
        tkinter.ttk.Button(
            buttons, text="录入所选账号数据库密钥", command=self._edit_account_keys
        ).pack(side="left", padx=5)

        if self.available_process_ids:
            pids = "、".join(str(pid) for pid in self.available_process_ids)
            tkinter.Label(
                self.account_picker_frame,
                text=f"当前检测到的 Weixin.exe PID：{pids}。程序会按所选数据库页校验密钥；目录与 PID 的对应关系不确定时，请手动核对账号目录。",
                font=("微软雅黑", 9), bg="#f7f8fa", fg="#64748b", wraplength=650,
            ).pack(pady=(8, 0))

    def _add_account_directory(self):
        selected = filedialog.askdirectory(
            parent=self.root, title="选择某一个微信账号的数据目录或 db_storage 目录"
        )
        if not selected:
            return
        selected = os.path.abspath(selected)
        if os.path.basename(selected).lower() == "db_storage":
            storage = selected
            account_dir = os.path.dirname(selected)
        elif os.path.isdir(os.path.join(selected, "db_storage")):
            account_dir = selected
            storage = os.path.join(selected, "db_storage")
        else:
            storage = filedialog.askdirectory(
                parent=self.root, title="请选择该账号的 db_storage 目录", initialdir=selected
            )
            if not storage:
                return
            account_dir = os.path.dirname(storage) if os.path.basename(storage).lower() == "db_storage" else selected

        if not (
            os.path.isfile(os.path.join(storage, "sns", "sns.db"))
            and os.path.isfile(os.path.join(storage, "contact", "contact.db"))
        ):
            messagebox.showerror("目录不完整", "所选目录没有同时找到 sns/sns.db 和 contact/contact.db。请重新选择该账号的 db_storage。")
            return

        folder_name = os.path.basename(account_dir.rstrip("\\\\ /"))
        wxid = folder_name if folder_name.startswith("wxid_") else simpledialog.askstring(
            "确认微信 ID", "该目录名未能识别为 wxid，请输入该账号的微信 ID：", parent=self.root
        )
        if not wxid:
            return
        display_name = simpledialog.askstring(
            "账号显示名称", "请输入微信昵称或自定义名称（可留空）：", initialvalue=wxid, parent=self.root
        ) or wxid
        profile = {
            "profile_id": self.account_profile_store.profile_id_for_path(account_dir),
            "weixin4": True,
            "account_dir": account_dir,
            "filePath": account_dir,
            "db_storage": storage,
            "dbStorage": storage,
            "wxid": wxid.strip(),
            "display_name": display_name.strip(),
            "displayName": display_name.strip(),
            "process_ids": self.available_process_ids[:],
            "availableProcessIds": self.available_process_ids[:],
        }
        self.account_profile_store.save_profile(profile)
        self.account_profiles.append(profile)
        self._render_account_picker()
        self.account_combo.current(len(self.account_profiles) - 1)

    def _edit_account_keys(self):
        index = self.account_combo.current() if self.account_combo else -1
        if index < 0 or index >= len(self.account_profiles):
            messagebox.showwarning("未选择账号", "请先选择一个账号。")
            return
        profile = self.account_profiles[index]
        profile_id = profile.get("profile_id") or self.account_profile_store.profile_id_for_path(profile.get("account_dir", ""))
        existing = self.account_profile_store.load_secrets(profile_id)
        if not profile.get("weixin4"):
            legacy_key = simpledialog.askstring(
                "数据库密钥",
                "输入所选旧版微信账号的数据库密钥；留空则保留现有值：",
                initialvalue=existing.get("legacy_db_key", ""), parent=self.root, show="*",
            )
            if legacy_key is None:
                return
            secrets = dict(existing)
            if legacy_key.strip():
                secrets["legacy_db_key"] = legacy_key.strip()
            if secrets:
                self.account_profile_store.save_secrets(profile_id, secrets)
            messagebox.showinfo("密钥设置", "密钥已使用 Windows DPAPI 加密保存。", parent=self.root)
            return
        sns_key = simpledialog.askstring(
            "Sns.db 数据库密钥",
            "输入该账号 Sns.db 的 64 位十六进制密钥；留空则保留现有值：",
            initialvalue=existing.get("sns_db_key", ""), parent=self.root, show="*",
        )
        if sns_key is None:
            return
        contact_key = simpledialog.askstring(
            "Contact.db 数据库密钥",
            "输入该账号 Contact.db 的 64 位十六进制密钥；留空则保留现有值：",
            initialvalue=existing.get("contact_db_key", ""), parent=self.root, show="*",
        )
        if contact_key is None:
            return
        secrets = dict(existing)
        if sns_key.strip():
            secrets["sns_db_key"] = sns_key.strip()
        if contact_key.strip():
            secrets["contact_db_key"] = contact_key.strip()
        if secrets:
            self.account_profile_store.save_secrets(profile_id, secrets)
        messagebox.showinfo(
            "密钥设置",
            "密钥已使用 Windows DPAPI 加密保存。不会以明文写入账号档案。图片和视频 CDN 密钥由每条朋友圈媒体记录提供，无需在此重复录入。",
            parent=self.root,
        )

    def _use_selected_account(self):
        index = self.account_combo.current() if self.account_combo else -1
        if index < 0 or index >= len(self.account_profiles):
            messagebox.showwarning("未选择账号", "请先选择一个账号。")
            return
        self._activate_account(self.account_profiles[index])

    def _activate_account(self, account_info):
        from datetime import datetime as _datetime

        profile = dict(account_info)
        account_dir = profile.get("account_dir") or profile.get("filePath") or profile.get("db_path") or ""
        profile_id = profile.get("profile_id") or self.account_profile_store.profile_id_for_path(account_dir)
        profile["profile_id"] = profile_id
        profile["account_dir"] = account_dir
        profile["filePath"] = profile.get("filePath") or account_dir
        profile["dbStorage"] = profile.get("dbStorage") or profile.get("db_storage") or ""
        profile["weixin4"] = bool(profile.get("weixin4"))
        workspace = self.account_profile_store.workspace_for(profile)
        profile["workspaceDir"] = str(workspace)
        profile["databaseCopyPath"] = str(workspace / "database")
        profile["cacheCopyPath"] = str(workspace / "media_cache" / "Sns" / "Cache")
        secrets = self.account_profile_store.load_secrets(profile_id)
        if secrets.get("legacy_db_key"):
            profile["key"] = secrets["legacy_db_key"]
        profile["manual_db_keys"] = bool(secrets.get("sns_db_key") or secrets.get("contact_db_key"))
        self.account_info = profile
        self.account_profile_store.save_profile({
            "profile_id": profile_id,
            "wxid": profile.get("wxid") or "",
            "display_name": profile.get("displayName") or profile.get("display_name") or "",
            "account_dir": account_dir,
            "db_storage": profile.get("dbStorage") or "",
            "weixin4": profile["weixin4"],
            "process_ids": profile.get("process_ids") or self.available_process_ids,
            "last_used": int(_datetime.now().timestamp()),
        })
        if self.account_picker_frame:
            self.account_picker_frame.destroy()
            self.account_picker_frame = None
        self._show_account_ready()

    def _show_account_ready(self):
        account_info = self.account_info or {}
        display_name = account_info.get("displayName") or account_info.get("wxid") or "所选账号"
        if account_info.get("weixin4"):
            self.waiting_label.config(text=f"已选择微信账号：{display_name}")
        else:
            self.waiting_label.config(text=f"已选择微信账号：{display_name}")

        self.auto_scroll_button_text = tkinter.StringVar()
        self.auto_scroll_button_text.set("自动浏览当前朋友圈")
        self.auto_scroll_button = tkinter.ttk.Button(
            self.root, textvariable=self.auto_scroll_button_text,
            command=self.open_auto_scroll_guide
        )
        self.auto_scroll_button.place(relx=0.5, rely=0.18, anchor='center')

        self.step_help = tkinter.Label(
            self.root,
            text="要所有人：自己打开自己的朋友圈。要某个人：自己打开那个人的朋友圈。\n"
                 "然后点「自动浏览当前朋友圈」，程序只滚动这个已经打开的窗口，不会自己搜索。\n"
                 "最近的内容已经在微信里：可以直接点「下一步」，把所选账号的数据复制到独立工作空间。",
            font=("微软雅黑", 10), justify="left", wraplength=680,
            bg="#f7f8fa", fg="#334155",
        )
        self.step_help.place(relx=0.5, rely=0.24, anchor="n")

        self.next_step_button = tkinter.ttk.Button(
            self.root, text="下一步", command=self.next_step, style="Primary.TButton"
        )
        self.next_step_button.place(relx=0.5, rely=0.94, anchor="center")

    def switch_account(self):
        if self.html_exporter_thread and not self.html_exporter_thread.stop_flag:
            messagebox.showwarning("导出进行中", "请先完成或停止当前导出任务，再切换账号。", parent=self.root)
            return
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable] + sys.argv[1:], close_fds=True)
            else:
                subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0])], close_fds=True)
        except OSError as exc:
            messagebox.showerror("切换失败", str(exc), parent=self.root)
            return
        self.root.destroy()

    def open_auto_scroll_guide(self):

        self.auto_scroll_guide = AutoScrollGuide(self.root)
        self.auto_scroll_guide.frame.place(relx=0.5, rely=0.62, anchor='center')

    def next_step(self):

        if self.page_stage == 1:

            if self.auto_scroll_guide and self.auto_scroll_guide.auto_thread:
                self.auto_scroll_guide.auto_thread.set_scrolling(False)

            self.auto_scroll_button.place_forget()
            if self.step_help:
                self.step_help.place_forget()
            self._show_step(2)

            if self.auto_scroll_guide and self.auto_scroll_guide.frame:
                self.auto_scroll_guide.frame.place_forget()

            if not (self.account_info and self.account_info.get("weixin4")):
                self.restart_note1 = tkinter.Label(self.root, text="请关闭微信客户端", fg="red")
                self.restart_note1.place(relx=0.5, rely=0.2, anchor='center')
                self.restart_note2 = tkinter.Label(self.root, text="然后点击下一步")
                self.restart_note2.place(relx=0.5, rely=0.3, anchor='center')
                self.page_stage = 2
                return
            self.page_stage = 2

        if self.page_stage == 2:

            if self.restart_note1:
                self.restart_note1.place_forget()
            if self.restart_note2:
                self.restart_note2.place_forget()
            self.waiting_label.place_forget()

            self.decrypter = DatabaseDecrypter(self, self.account_info.get("filePath"), self.account_info.get("key"))

            if not self.decrypt_note:
                self.decrypt_note_text = tkinter.StringVar()
                self.decrypt_note = tkinter.Label(self.root, textvariable=self.decrypt_note_text)
                self.decrypt_note.place(relx=0.5, rely=0.2, anchor='center')
                self.decrypt_progressbar = tkinter.ttk.Progressbar(self.root)
                self.decrypt_progressbar.place(relx=0.5, rely=0.3, anchor='center')
                self.decrypt_progressbar['maximum'] = 100
            self.decrypt_note_text.set("正在复制数据.....")
            self.decrypt_progressbar['value'] = 0
            self.next_step_button.config(state=tkinter.DISABLED)
            if self.decrypter.decrypt():
                self.page_stage = 3
            return
        if self.page_stage == 3:
            self.decrypt_note.place_forget()
            self.decrypt_progressbar.place_forget()
            self.init_export_page()
            # 不再有下一步按钮
            self.next_step_button.place_forget()
            # 初始化视频导出器
            cache_copy_path = self.account_info.get("cacheCopyPath")
            self.video_decrypter = VideoDecrypter(
                self, self.account_info.get("filePath"), cache_path=cache_copy_path
            )
            # 初始化图片导出器
            self.image_decrypter = ImageDecrypter(
                self, self.account_info.get("filePath"), cache_path=cache_copy_path
            )
            self.page_stage = 4

    def init_export_page(self):

        from app.DataBase import micro_msg_db
        contact_datas = micro_msg_db.get_contact()

        contacts = []
        for c in contact_datas:
            contact = Contact(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[9], c[10], c[11])
            contacts.append(contact)

        def validate_contact(this_contact: Contact):
            c_type = this_contact.type
            user_name: str = this_contact.userName

            # 不是其他号码
            is_misc_account = c_type == 1 or c_type == 33 or c_type == 513
            # 不是公众号
            is_gh_account = user_name.startswith("gh_")
            # 不是聊天群
            is_chatroom = user_name.endswith("@chatroom")
            # 不是文件传输助手
            is_filehelper = this_contact.userName == "filehelper"
            return (not is_misc_account) and (not is_gh_account) and (not is_chatroom) and (not is_filehelper)

        filtered = filter(validate_contact, contacts)
        contacts = list(filtered)

        self._show_step(3)
        self.listbox = ListboxWithSearch(self.root, contacts)
        self.listbox.frame.place(relx=0.03, rely=0.10)

        self.export_panel = tkinter.LabelFrame(
            self.root, text="导出范围", font=("微软雅黑", 10), padx=12, pady=8, bg="#f7f8fa"
        )
        self.export_panel.place(relx=0.60, rely=0.10, relwidth=0.36, relheight=0.84)
        tkinter.ttk.Button(
            self.export_panel, text="切换微信账号", command=self.switch_account
        ).pack(anchor="w", pady=(0, 6))

        self.begin_calendar_label = tkinter.ttk.Label(self.export_panel, text="开始日期")
        self.begin_calendar_label.pack(anchor="w", pady=(4, 2))

        # 默认开始时间是100天前
        current_date = datetime.now()
        half_year_ago = current_date - timedelta(days=100)
        self.begin_calendar = tkcalendar.DateEntry(master=self.export_panel, locale="zh_CN", year=half_year_ago.year,
                                                   month=half_year_ago.month, day=half_year_ago.day,
                                                   maxdate=datetime.now())
        self.begin_calendar.pack(anchor="w", fill="x")

        self.end_calendar_label = tkinter.ttk.Label(self.export_panel, text="截止日期")
        self.end_calendar_label.pack(anchor="w", pady=(10, 2))
        self.end_calendar = tkcalendar.DateEntry(master=self.export_panel, locale="zh_CN", maxdate=datetime.now())
        self.end_calendar.pack(anchor="w", fill="x")

        range_note = tkinter.Label(
            self.export_panel,
            text="左侧勾选好友。只导出这个日期范围内的朋友圈。",
            font=("微软雅黑", 9),
            wraplength=210,
            justify="left",
            bg="#f7f8fa",
            fg="#5c6b80",
        )
        range_note.pack(anchor="w", pady=(12, 8))

        self.convert_video_var = tkinter.IntVar(value=0)
        self.convert_video = tkinter.ttk.Checkbutton(self.export_panel, text='视频转码', variable=self.convert_video_var)
        self.convert_video.pack(anchor="w")
        ToolTip(self.convert_video,
                "视频原始格式为H265,只支持\nChrome浏览器播放，勾选后\n将视频转码为H264,支持大\n部分浏览器，但导出速度变慢")
        convert_note = tkinter.Label(
            self.export_panel,
            text="不勾选时视频是 H.265，Chrome 可以播放。勾选后转成 H.264，导出更慢，更多浏览器能播。",
            font=("微软雅黑", 9),
            wraplength=210,
            justify="left",
            bg="#f7f8fa",
            fg="#5c6b80",
        )
        convert_note.pack(anchor="w", pady=(4, 10))

        self.confirm_button_text = tkinter.StringVar()
        self.confirm_button_text.set("开始导出")

        self.confirm_button = tkinter.ttk.Button(
            self.export_panel, textvariable=self.confirm_button_text,
            command=self.confirm_export, style="Primary.TButton"
        )
        self.confirm_button.pack(anchor="w", pady=(4, 6))

        # 进度条在警告上面，避免挡住停止导出
        self.export_progressbar = tkinter.ttk.Progressbar(self.export_panel, length=200)

        self.warning_label = tkinter.Label(
            self.export_panel, fg="red", wraplength=210, justify="left", bg="#f7f8fa", font=("微软雅黑", 9)
        )
        self.warning_label.pack(anchor="w", pady=(6, 0))

        # 导出成功的提示
        self.succeed_label = tkinter.Label(self.export_panel, text="导出结束", bg="#f7f8fa", font=("微软雅黑", 10))
        self.succeed_label_2 = tkinter.Label(
            self.export_panel, text="打开文件夹", fg="#2563eb", cursor="hand2", bg="#f7f8fa", font=("微软雅黑", 10)
        )
        self.succeed_label_2.bind("<Button-1>", self.open_target_folder)

    def confirm_export(self):

        if self.html_exporter_thread and not self.html_exporter_thread.stop_flag:
            self.html_exporter_thread.stop()
        else:
            if not self.warning_label:
                self.warning_label = tkinter.Label(self.root, fg="red", wraplength=210, justify="left")
            self.warning_label.config(text="")
            contacts = self.listbox.get_contacts()
            if not contacts:
                self.warning_label.config(text=f"请选择至少一个联系人")
                return

            if self.begin_calendar.get_date() > self.end_calendar.get_date():
                self.warning_label.config(text=f"开始时间必须小于截止时间")
                return

            if not self.export_progressbar.winfo_ismapped():
                self.export_progressbar.pack(anchor="w", fill="x", pady=(8, 0), before=self.warning_label)
            # 进度值最大值
            self.export_progressbar['maximum'] = 100
            # 进度值初始值
            self.export_progressbar['value'] = 0

            current_time = datetime.now()
            account_name = (
                self.account_info.get("displayName")
                or self.account_info.get("display_name")
                or self.account_info.get("wxid")
                or ""
            )
            if not account_name:
                account_name = simpledialog.askstring(
                    "导出目录名称", "请输入账号名称，用于生成导出文件夹：", parent=self.root
                ) or "微信账号"
            account_name = re.sub(r'[<>:"/\\\\|?*]+', "_", str(account_name)).strip(" ._") or "微信账号"
            self.export_dir_name = current_time.strftime("%Y_%m_%d_%H%M%S") + "_" + account_name
            contact_map = {contact.userName: contact for contact in contacts}

            self.confirm_button_text.set("停止导出")
            self.succeed_label.pack_forget()
            self.succeed_label_2.pack_forget()

            # 导出线程
            self.html_exporter_thread = HtmlExporter(self, self.export_dir_name, contact_map,
                                                     self.begin_calendar.get_date(), self.end_calendar.get_date(),
                                                     self.convert_video_var.get())
            self.html_exporter_thread.start()

    def update_decrypt_progressbar(self, progress):
        self.decrypt_progressbar['value'] = progress
        self.root.update()

    def update_export_progressbar(self, progress):
        self.export_progressbar['value'] = progress
        self.root.update()

    def show_export_warning(self, text):
        if not self.warning_label:
            self.warning_label = tkinter.Label(self.root, fg="red", wraplength=210, justify="left")
        self.warning_label.config(text=text, wraplength=210, justify="left")
        try:
            self.root.update()
        except tkinter.TclError:
            pass

    def export_succeed(self):
        self.confirm_button_text.set("开始导出")
        self.succeed_label.pack(anchor="w", pady=(8, 0))
        self.succeed_label_2.pack(anchor="w")

    def open_target_folder(self, event):
        folder_path = Path(f"output/{self.export_dir_name}/")
        # 转换为绝对路径
        absolute_path = folder_path.resolve()
        os.startfile(absolute_path)
