import os
import re
import subprocess
import sys
import tkinter
import tkinter.messagebox
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

        self.account_info = account_info
        display = str(account_info.get("display_name") or account_info.get("wxid") or "所选账号")
        wxid = str(account_info.get("wxid") or "")
        version = "微信 4.x" if account_info.get("weixin4") else "微信 3.x"
        self.waiting_label.config(text=f"已选择 {display}  ·  {wxid}  ·  {version}")
        self.switch_account_button = tkinter.ttk.Button(
            self.root, text="切换账号", command=self.switch_account
        )
        self.switch_account_button.place(relx=0.92, rely=0.11, anchor="e")

        self.auto_scroll_button_text = tkinter.StringVar()
        self.auto_scroll_button_text.set("自动浏览当前朋友圈")
        self.auto_scroll_button = tkinter.ttk.Button(self.root, textvariable=self.auto_scroll_button_text,
                                                     command=self.open_auto_scroll_guide)
        self.auto_scroll_button.place(relx=0.5, rely=0.18, anchor='center')

        self.step_help = tkinter.Label(
            self.root,
            text="要所有人：自己打开自己的朋友圈。要某个人：自己打开那个人的朋友圈。\n"
                 "然后点「自动浏览当前朋友圈」，程序只滚动这个已经打开的窗口，不会自己搜索。\n"
                 "最近的内容已经在微信里：可以直接点「下一步」，把数据复制到本机。",
            font=("微软雅黑", 10),
            justify="left",
            wraplength=680,
            bg="#f7f8fa",
            fg="#334155",
        )
        self.step_help.place(relx=0.5, rely=0.24, anchor="n")

        self.next_step_button = tkinter.ttk.Button(
            self.root, text="下一步", command=self.next_step, style="Primary.TButton"
        )
        self.next_step_button.place(relx=0.5, rely=0.94, anchor="center")



    def switch_account(self):
        if self.html_exporter_thread and self.html_exporter_thread.is_alive():
            tkinter.messagebox.showwarning("无法切换", "请先完成或停止当前账号的导出。")
            return
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable], close_fds=True)
            else:
                subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0])], close_fds=True)
            self.root.destroy()
        except Exception as exc:
            tkinter.messagebox.showerror("切换失败", str(exc))

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

            # 多账号档案使用用户指定的目录和密钥；不要求关闭其他常驻微信实例。
            # 复制期间建议不要在所选账号中大量新增媒体，以降低数据库快照发生变化的概率。
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
                try:
                    from helper.multi_account_runtime import activate_account_database
                    database_dir = (self.account_info or {}).get("databaseDir") or self.decrypter.output_dir
                    activate_account_database(database_dir)
                    self.page_stage = 3
                except Exception as exc:
                    self.decrypt_note_text.set(f"账号数据库切换失败：{exc}")
                    self.next_step_button.config(state=tkinter.NORMAL)
            return
        if self.page_stage == 3:
            self.decrypt_note.place_forget()
            self.decrypt_progressbar.place_forget()
            self.init_export_page()
            # 不再有下一步按钮
            self.next_step_button.place_forget()
            # 初始化视频导出器
            self.video_decrypter = VideoDecrypter(self, self.account_info.get("filePath"))
            # 初始化图片导出器
            self.image_decrypter = ImageDecrypter(self, self.account_info.get("filePath"))
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
            display_name = str((self.account_info or {}).get("display_name") or "")
            wxid = str((self.account_info or {}).get("wxid") or "")
            try:
                from app.DataBase import micro_msg_db
                own_contact = micro_msg_db.get_contact_by_username(wxid) if wxid else None
                if own_contact:
                    actual_name = str(own_contact[4] or "").strip() if len(own_contact) > 4 else ""
                    actual_remark = str(own_contact[3] or "").strip() if len(own_contact) > 3 else ""
                    display_name = actual_name or actual_remark or display_name
            except Exception:
                pass
            display_name = display_name or wxid or "微信账号"
            safe_name = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1f]', "_", display_name).strip(" ._")
            safe_wxid = re.sub(r'[^A-Za-z0-9_.-]', "_", wxid)[:24]
            suffix = f"_{safe_wxid}" if safe_wxid else ""
            self.export_dir_name = current_time.strftime("%Y_%m_%d_%H%M%S") + f"_{safe_name or '微信账号'}" + suffix
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
