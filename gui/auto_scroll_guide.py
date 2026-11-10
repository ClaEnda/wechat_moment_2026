import tkinter
import tkinter.ttk

from entity.contact import Contact
from helper.auto_scroll import AutoScroll
from helper.moments_window import find_moments_window


class AutoScrollGuide:

    def __init__(self, root, gui=None):
        self.flood_moments_note = None
        self.auto_thread = None
        self.frame = tkinter.LabelFrame(root)
        self.gui = gui
        self.target_pid = None
        if gui and getattr(gui, "account_info", None):
            info = gui.account_info
            self.target_pid = info.get("process_id")
            if self.target_pid is None and info.get("process_ids"):
                self.target_pid = info["process_ids"][0]

        self.open_moments_guide = tkinter.Label(
            self.frame,
            text="请自己打开朋友圈窗口\n所有人就打开自己的，某个人就打开那个人的",
            font=("微软雅黑", 10),
        )
        self.open_moments_guide.pack()

        image = tkinter.PhotoImage(file='resource/gui_pictures/open_moments_guide.png')
        self.open_moments_guide_image = tkinter.Label(self.frame, image=image)
        self.open_moments_guide_image.image = image
        self.open_moments_guide_image.pack()

        self.auto_scroll_button_text = tkinter.StringVar()
        self.auto_scroll_button_text.set("开始")

        self.auto_scroll_button = tkinter.ttk.Button(self.frame, textvariable=self.auto_scroll_button_text,
                                                     command=self.switch_auto_scroll)
        self.auto_scroll_button.pack(pady=5)
        self.missing_note = tkinter.Label(self.frame, text="", fg="#c2410c", font=("微软雅黑", 10))
        self.missing_note.pack()

    def switch_auto_scroll(self):

        if self.auto_thread is None:
            moments_hwnd = find_moments_window(self.target_pid)
            if moments_hwnd != 0:
                self.missing_note.config(text="")
                self.auto_thread = AutoScroll(self, moments_hwnd, self.target_pid)
                self.flood_moments_note = tkinter.Label(self.frame, text="正在自动读取朋友圈数据......."
                                                                         "\n可将窗口最小化，后台自动执行"
                                                                         "\n可随时查看进度，可随时停止")
                self.flood_moments_note.pack()
                self.auto_thread.start()
                self.auto_scroll_button_text.set("停止")
            else:
                if self.target_pid is None:
                    self.missing_note.config(text="没有绑定该账号的微信 PID，且检测到窗口不唯一。请在账号档案中填写对应 PID。")
                else:
                    self.missing_note.config(text="未找到该 PID 对应的朋友圈窗口，请在所选微信实例中打开朋友圈。")
        else:
            if self.auto_thread.scrolling:
                self.auto_scroll_button_text.set("继续")
                self.auto_thread.set_scrolling(False)
            else:
                self.auto_scroll_button_text.set("停止")
                self.auto_thread.set_scrolling(True)
