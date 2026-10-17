import random
import threading
import time

import pywintypes

from helper.moments_window import find_moments_window, scroll_moments


class AutoScroll(threading.Thread):

    def __init__(self, gui, moments_hwnd):
        self.gui = gui
        self.moments_hwnd = moments_hwnd
        self.scrolling = False
        super().__init__()

    def run(self) -> None:
        self.scrolling = True
        while True:
            if self.scrolling:
                try:
                    scroll_moments(self.moments_hwnd)
                    self.gui.flood_moments_note.pack()
                    time.sleep(random.uniform(0.7, 0.8))
                except pywintypes.error:
                    self.moments_hwnd = find_moments_window()
                    self.gui.flood_moments_note.pack_forget()
                    time.sleep(1)
            else:
                self.gui.flood_moments_note.pack_forget()
                time.sleep(1)

    def set_scrolling(self, scrolling: bool) -> None:
        self.scrolling = scrolling
