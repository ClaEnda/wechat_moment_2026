import time
import tkinter
import tkinter.ttk

import win32con
import win32gui

from helper.auto_scroll_single import AutoScrollSingle
from helper.moments_window import find_window_by_class_pid


class AutoScrollSingleGuide:

    def __init__(self, root, gui=None):
        self.working_note = None
        self.auto_thread = None
        self.frame = tkinter.LabelFrame(root)
        self.gui = gui
        self.target_pid = None
        if gui and getattr(gui, 'account_info', None):
            info = gui.account_info
            self.target_pid = info.get('process_id')
            if self.target_pid is None and info.get('process_ids'):
                self.target_pid = info['process_ids'][0]

        self.guide = tkinter.Label(self.frame, text="请打开搜一搜窗口\n点击开始后不要操作键鼠")
        self.guide.pack()

        self.search_username = tkinter.Entry(self.frame, width=12)
        self.search_username.insert(0, '请输入好友昵称')
        self.search_username.config(fg='grey')
        self.search_username.bind('<FocusIn>', self.on_search_username_click)
        self.search_username.pack()

        image = tkinter.PhotoImage(file='resource/gui_pictures/open_search_guide.png')
        self.guide_image = tkinter.Label(self.frame, image=image)
        self.guide_image.image = image
        self.guide_image.pack()

        self.button_text = tkinter.StringVar()
        self.button_text.set("开始")

        self.button = tkinter.ttk.Button(self.frame, textvariable=self.button_text,
                                         command=self.switch_auto_scroll_single)
        self.button.pack(pady=5)
        self.missing_note = tkinter.Label(self.frame, text="", fg="#c2410c", font=("微软雅黑", 10))
        self.missing_note.pack()

    def on_search_username_click(self, event):
        if self.search_username.get() == '请输入好友昵称':
            self.search_username.delete(0, tkinter.END)
            self.search_username.config(fg='black')

    def switch_auto_scroll_single(self):

        search_hwnd = find_window_by_class_pid("Chrome_WidgetWin_0", "微信", self.target_pid)
        wechat_hwnd = find_window_by_class_pid("WeChatMainWndForPC", "微信", self.target_pid)

        search_username = self.search_username.get()

        if self.auto_thread is None:
            if search_username == '请输入好友昵称' or search_username == '':
                self.search_username.config(fg='red')
                return
            if search_hwnd != 0 and wechat_hwnd != 0:
                self.missing_note.config(text="")
                self.auto_thread = AutoScrollSingle(self, search_hwnd, search_username, self.target_pid)
                self.working_note = tkinter.Label(self.frame, text="正在自动读取朋友圈数据......."
                                                                   "\n请不要遮挡搜一搜窗口")


                self.working_note.pack()
                self.auto_thread.start()
                self.button_text.set("停止")
            else:
                self.missing_note.config(text="请先打开微信的搜一搜窗口")
        else:
            if self.auto_thread.scrolling:
                self.button_text.set("开始")
                self.auto_thread.set_scrolling(False)
                self.auto_thread = None
            else:
                self.button_text.set("停止")
                self.switch_auto_scroll_single()
