import datetime
import hashlib
import json
import shutil
import tempfile
import threading
import time
from typing import Tuple

import xmltodict

import os
from openpyxl import Workbook

from entity.comment import Comment
from entity.contact import Contact
from exporter.avatar_exporter import AvatarExporter
from exporter.emoji_exporter import EmojiExporter
from exporter.image_exporter import ImageExporter
from exporter.video_exporter import VideoExporter
from exporter.sns_interactions import render_interactions_html
from log import LOG
from entity.moment_msg import MomentMsg
from pathlib import Path


def get_img_div_css(size: int) -> str:
    if size == 1:
        return "width:10rem; overflow:hidden"
    else:
        return "width:19rem; overflow:hidden"


def get_live_box_css(size: int) -> str:
    if size == 1:
        return "width:10rem;height:10rem;"
    elif size == 2 or size == 4:
        return "width:8rem;height:8rem;float:left;margin-bottom:0.2rem;margin-right:0.2rem;"
    else:
        return "width:5rem;height:5rem;float:left;margin-bottom:0.2rem;margin-right:0.2rem;"


def get_img_css(size: int) -> str:
    """object-fit: cover; 预览图居中裁剪
    cursor:pointer; 手形鼠标
    """
    img_style = "object-fit:cover;cursor:pointer;"
    if size == 1:
        return f"width:10rem;height:10rem;{img_style}"
    elif size == 2:
        return f"width:8rem;height:8rem;float:left;margin-bottom:0.2rem;margin-right:0.2rem;{img_style}"
    elif size == 4:
        return f"width:8rem;height:8rem;float:left;margin-bottom:0.2rem;margin-right:0.2rem;{img_style}"
    else:
        return f"width:5rem;height:5rem;float:left;margin-bottom:0.2rem;margin-right:0.2rem;{img_style}"


def is_music_msg(msg: MomentMsg) -> bool:
    """判断一个msg是否为音乐分享"""
    if (
        msg.timelineObject.ContentObject
        and msg.timelineObject.ContentObject.mediaList
        and msg.timelineObject.ContentObject.mediaList.media
    ):
        media = msg.timelineObject.ContentObject.mediaList.media[0]
        if media.type == "5":
            return True
    return False


def live_media_by_index(msg_dict: dict) -> list:
    """按媒体下标取出实况短视频。没有实况的位置是 None。"""
    from entity.moment_msg import Media

    timeline = msg_dict.get("TimelineObject") or {}
    content = timeline.get("ContentObject") or {}
    media_list = content.get("mediaList") or {}
    media = media_list.get("media") or []
    if isinstance(media, dict):
        media = [media]
    known = {"type", "id", "url", "thumb", "thumbUrl", "videoDuration", "title", "description", "enc"}
    result = []
    for item in media:
        live = None
        block = item.get("LivePhoto") if isinstance(item, dict) else None
        raw = block.get("liveMedia") if isinstance(block, dict) else None
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        if isinstance(raw, dict):
            slim = {key: value for key, value in raw.items() if key in known}
            try:
                live = Media.from_json(json.dumps(slim))
            except Exception:
                live = None
        result.append(live)
    return result


def render_images_html(images: list[Tuple]) -> str:
    html = f'     <div style="{get_img_div_css(len(images))}">\n'
    for thumb_path, image_path, live_path in images:
        if live_path:
            html += (
                f'     <div class="live_box" style="{get_live_box_css(len(images))}"'
                f' onmouseenter="playLive(event)" onmouseleave="stopLive(event)">\n'
            )
            html += (
                f'       <img src="{thumb_path}" full_img="{image_path}"'
                f' data-live="{live_path}" onclick="openFullSize(event)" />\n'
            )
            html += (
                f'       <video class="live_video" playsinline loop preload="metadata"'
                f' src="{live_path}"></video>\n'
            )
            html += "       <span class=\"live_badge\">实况</span>\n"
            html += "     </div>\n"
        else:
            html += f"""     <img src="{thumb_path}" full_img="{image_path}" onclick="openFullSize(event)" 
                                 style="{get_img_css(len(images))}"/>\n"""
    html += "      </div>\n"
    return html


def get_music_info(msg: MomentMsg) -> Tuple[str, str, str]:
    """获取音乐标题，演唱者，音乐源"""
    title = ""
    musician = ""
    src = ""
    if (
        msg.timelineObject.ContentObject
        and msg.timelineObject.ContentObject.mediaList
        and msg.timelineObject.ContentObject.mediaList.media
    ):
        media = msg.timelineObject.ContentObject.mediaList.media[0]
        title = media.title
        musician = media.description
        if media.url:
            src = media.url.text
    return title, musician, src


class HtmlExporter(threading.Thread):

    def __init__(
        self,
        gui: "Gui",
        dir_name: str,
        contacts_map: dict[str, Contact],
        begin_date: datetime.date,
        end_date: datetime.date,
        convert_video: int,
    ):
        self.dir_name = dir_name
        if Path(f"output/{self.dir_name}").exists():
            shutil.rmtree(f"output/{self.dir_name}")
        shutil.copytree("resource/template/", f"output/{self.dir_name}")

        self.gui = gui
        self.avatar_exporter = AvatarExporter(dir_name)
        self.image_exporter = ImageExporter(dir_name)
        self.video_exporter = VideoExporter(dir_name, convert_video)
        self.html_head = None
        self.html_end = None
        self.file = None
        self.outwb = None
        self.outws = None
        self.output_folder = None
        self.contacts_map = contacts_map
        self.begin_date = begin_date
        self.end_date = end_date
        self.convert_video = convert_video
        self.stop_flag = False
        self._owner_image_md5: set[str] = set()
        self._interaction_name_cache: dict[str, str] = {}
        super().__init__()

    def _resolve_interaction_name(self, username: str) -> str:
        """优先使用本地备注，其次使用微信昵称；不联网查询联系人信息。"""
        username = str(username or "").strip()
        if not username:
            return "未知用户"

        account_info = getattr(self.gui, "account_info", None) or {}
        if username == str(account_info.get("wxid") or ""):
            return "我"

        selected = self.contacts_map.get(username)
        if selected:
            name = str(selected.remark or "").strip() or str(selected.nickName or "").strip()
            if name:
                return name

        if username in self._interaction_name_cache:
            return self._interaction_name_cache[username]

        display_name = username
        try:
            from app.DataBase import micro_msg_db

            contact = micro_msg_db.get_contact_by_username(username)
            if contact:
                remark = str(contact[3] or "").strip() if len(contact) > 3 else ""
                nickname = str(contact[4] or "").strip() if len(contact) > 4 else ""
                display_name = remark or nickname or username
        except Exception:
            # 联系人表缺失或此账号未缓存时，保留 wxid 作为可追溯的回退值。
            display_name = username

        self._interaction_name_cache[username] = display_name
        return display_name

    def _load_earlier_moments(self) -> None:
        """开始日期早于本地缓存时，滚动已打开的朋友圈并重新复制数据库。"""
        account = getattr(self.gui, "account_info", None) or {}
        if not account.get("weixin4"):
            return
        earliest = self._earliest_local_date()
        if earliest and earliest <= self.begin_date:
            return

        from helper.moments_window import find_moments_window

        hwnd = find_moments_window()
        if not hwnd:
            self._warn_cached_range(earliest, False)
            return

        stop_scroll = threading.Event()
        holder = {"hwnd": hwnd}

        def pump():
            while not stop_scroll.is_set() and not self.stop_flag:
                holder["hwnd"] = self._scroll_once(holder["hwnd"])
                time.sleep(0.6)

        worker = threading.Thread(target=pump, daemon=True)
        self._bring_moments_forward(hwnd)
        worker.start()
        last = earliest
        stall = 0
        try:
            while not self.stop_flag and stall < 3:
                shown = last.strftime("%Y-%m-%d") if last else "未知"
                self.gui.show_export_warning(f"正在向前浏览朋友圈，本地最早到 {shown}")
                self._wait_scroll(12)
                if self.stop_flag or not holder["hwnd"]:
                    break
                try:
                    self._refresh_local_databases()
                except Exception:
                    LOG.error("更新本地朋友圈失败")
                    self._reopen_local_databases()
                    break
                earliest = self._earliest_local_date()
                if earliest and earliest <= self.begin_date:
                    self.gui.show_export_warning("")
                    return
                if earliest == last:
                    stall += 1
                else:
                    stall = 0
                    last = earliest
            if not self.stop_flag:
                self._warn_cached_range(self._earliest_local_date() or last, bool(holder["hwnd"]))
        finally:
            stop_scroll.set()
            worker.join(timeout=2)

    def _scroll_once(self, hwnd: int) -> int:
        import pywintypes
        import win32gui

        from helper.moments_window import find_moments_window, scroll_moments

        if not hwnd or not win32gui.IsWindow(hwnd):
            hwnd = find_moments_window()
        if not hwnd:
            return 0
        try:
            scroll_moments(hwnd, 10)
        except pywintypes.error:
            return find_moments_window()
        return hwnd

    def _bring_moments_forward(self, hwnd: int) -> None:
        import win32con
        import win32gui

        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _wait_scroll(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not self.stop_flag:
            time.sleep(0.2)

    def _refresh_local_databases(self) -> None:
        from decrypter.weixin4 import build_export_databases

        previous = self._earliest_local_date()
        sns_path = os.path.join("app", "DataBase", "Msg", "Sns.db")
        backup = self._backup_sns(sns_path)
        self._close_local_databases()

        def progress(value, _text):
            self.gui.update_export_progressbar(min(int(value), 20))

        try:
            build_export_databases(self.gui.account_info, progress)
        except Exception:
            self._restore_sns(backup, sns_path)
            self._reopen_local_databases()
            raise
        self._reopen_local_databases()
        current = self._earliest_local_date()
        if previous and (current is None or current > previous):
            self._close_local_databases()
            self._restore_sns(backup, sns_path)
            self._reopen_local_databases()
            raise RuntimeError("刷新后的朋友圈比原来更少")
        self._discard_backup(backup)

    def _backup_sns(self, sns_path: str):
        if not os.path.isfile(sns_path):
            return None
        fd, backup = tempfile.mkstemp(prefix="sns-scroll-", suffix=".db")
        os.close(fd)
        try:
            shutil.copy2(sns_path, backup)
        except Exception:
            os.remove(backup)
            raise
        return backup

    def _restore_sns(self, backup, sns_path: str) -> None:
        if backup and os.path.isfile(backup):
            shutil.copy2(backup, sns_path)
            os.remove(backup)

    def _discard_backup(self, backup) -> None:
        if backup and os.path.isfile(backup):
            os.remove(backup)

    def _close_local_databases(self) -> None:
        from app.DataBase import micro_msg_db, msg_db, sns_db

        for database in (sns_db, micro_msg_db, msg_db):
            database.close()

    def _reopen_local_databases(self) -> None:
        from app.DataBase import micro_msg_db, msg_db, sns_db

        for database in (sns_db, micro_msg_db, msg_db):
            if not database.open_flag:
                database.init_database()

    def _earliest_local_date(self):
        from app.DataBase import sns_db

        if not sns_db.open_flag:
            sns_db.init_database()
        stamp = sns_db.get_earliest_timestamp()
        if not stamp:
            return None
        if stamp > 10**12:
            stamp = stamp / 1000
        return datetime.datetime.fromtimestamp(stamp).date()

    def _warn_cached_range(self, earliest, window_open: bool) -> None:
        if earliest:
            shown = earliest.strftime("%Y-%m-%d")
            if window_open:
                text = f"本地朋友圈只缓存到 {shown}，更早的内容还没有加载进来"
            else:
                text = f"朋友圈窗口未打开，本地最早只到 {shown}。请打开朋友圈窗口后重新导出"
        else:
            text = "本地还没有朋友圈记录。请打开朋友圈窗口后重新导出"
        self.gui.show_export_warning(text)

    def run(self) -> None:
        self._load_earlier_moments()
        if self.stop_flag:
            self.gui.export_succeed()
            return

        # 创建excel文件
        self.outwb = Workbook()
        self.outws = self.outwb.worksheets[0]
        # 先添加一行表头
        self.outws.append(
            [
                "time",
                "username",
                "remark",
                "avatarPath",
                "contentDesc",
                "images",
                "videos",
                "location",
                "likes",
                "comments",
            ]
        )
        self.output_folder = f"output/{self.dir_name}/excel/"
        os.mkdir(self.output_folder)

        with open(f"resource/template.html", encoding="utf-8") as f:
            content = f.read()
            self.html_head, self.html_end = content.split("/*内容分割线*/")
        self.file = open(f"output/{self.dir_name}/index.html", "w", encoding="utf-8")

        my_name = ""
        my_avatar = ""
        wxid = ""
        if self.gui.account_info:
            wxid = self.gui.account_info.get("wxid") or ""
        if wxid:
            my_avatar = self.avatar_exporter.get_avatar_path(wxid) or ""
            from app.DataBase import micro_msg_db

            my_info = micro_msg_db.get_contact_by_username(wxid)
            if my_info and len(my_info) > 4 and my_info[4]:
                my_name = str(my_info[4])
        self.html_head = self.html_head.replace("{my_avatar}", my_avatar)
        self.html_head = self.html_head.replace("{my_wxid}", "")
        self.html_head = self.html_head.replace("{my_name}", my_name)

        self.file.write(self.html_head)
        from app.DataBase import sns_db

        # 加一天
        end_date = self.end_date + datetime.timedelta(days=1)
        begin_time = time.mktime(
            datetime.datetime(
                self.begin_date.year, self.begin_date.month, self.begin_date.day
            ).timetuple()
        )
        end_time = time.mktime(
            datetime.datetime(end_date.year, end_date.month, end_date.day).timetuple()
        )

        self.gui.image_decrypter.decrypt_images(
            self, self.begin_date, end_date, self.dir_name
        )
        self.gui.video_decrypter.decrypt_videos(
            self, self.begin_date, end_date, self.dir_name, self.convert_video
        )

        message_datas = sns_db.get_messages_in_time(begin_time, end_time)
        for index, message_data in enumerate(message_datas):
            if not self.stop_flag:
                if message_data[0] in self.contacts_map:
                    interactions_data = sns_db.get_interactions_by_feed_id(message_data[2])
                    comments: list[Comment] = [
                        Comment.from_db_row(row) for row in interactions_data or []
                    ]
                    try:
                        self.export_msg(message_data[1], comments, self.contacts_map)
                    except Exception:
                        LOG.error("跳过一条无法解析的朋友圈")
                    # 更新进度条 前30%视频处理  后70%其他处理
                    progress = round(index / len(message_datas) * 70)
                    self.gui.update_export_progressbar(30 + progress)
        self.gui.update_export_progressbar(100)
        self.finish_file()
        self.gui.export_succeed()

    def stop(self) -> None:
        self.stop_flag = True

    def _remember_owner_images(self, username: str, images: list[Tuple]) -> None:
        wxid = ""
        if self.gui and getattr(self.gui, "account_info", None):
            wxid = self.gui.account_info.get("wxid") or ""
        if not wxid or username != wxid:
            return
        for _thumb_path, image_path, _live_path in images:
            file_path = Path(f"output/{self.dir_name}") / image_path
            try:
                self._owner_image_md5.add(hashlib.md5(file_path.read_bytes()).hexdigest())
            except OSError:
                continue

    def _resolve_cover_path(self) -> str:
        """数据库里的封面地址优先。否则用和自己动态同一张图的本地背景，避开别人的缓存。"""
        from app.DataBase import sns_db

        cover_url = sns_db.get_cover_url()
        if cover_url:
            saved = self.image_exporter.save_image((cover_url, "", ""), "image")
            if saved:
                return saved
        return self._cover_from_local_bkg()

    def _cover_from_local_bkg(self) -> str:
        account = ""
        if self.gui and getattr(self.gui, "account_info", None):
            account = self.gui.account_info.get("filePath") or ""
        if not account:
            return ""
        bkg_dir = Path(account) / "business" / "sns" / "bkg"
        if not bkg_dir.is_dir():
            return ""
        cached = []
        for file in bkg_dir.rglob("*"):
            if not file.is_file():
                continue
            try:
                data = file.read_bytes()
                mtime = file.stat().st_mtime
            except OSError:
                continue
            if not data.startswith(b"\xff\xd8\xff"):
                continue
            cached.append((mtime, hashlib.md5(data).hexdigest(), data))
        if not cached:
            return ""
        images_dir = Path(f"output/{self.dir_name}/images")
        images_dir.mkdir(parents=True, exist_ok=True)
        exported = {}
        for existing in images_dir.iterdir():
            if not existing.is_file() or existing.name == "cover.jpg":
                continue
            try:
                exported[hashlib.md5(existing.read_bytes()).hexdigest()] = existing.name
            except OSError:
                continue
        owner_hits = [item for item in cached if item[1] in self._owner_image_md5]
        exported_hits = [item for item in cached if item[1] in exported]
        pool = owner_hits or exported_hits or cached
        _mtime, digest, data = max(pool, key=lambda item: item[0])
        if digest in exported:
            return f"images/{exported[digest]}"
        destination = images_dir / "cover.jpg"
        destination.write_bytes(data)
        return "images/cover.jpg"

    def export_msg(
        self, message: str, comments: list[Comment], contacts_map: dict[str, Contact]
    ) -> None:

        LOG.info("导出一条朋友圈")
        # force_list: 强制要求转media为list
        msg_dict = xmltodict.parse(message, force_list={"media"})
        msg_json = json.dumps(msg_dict)
        msg = MomentMsg.from_json(msg_json)
        # print("msg:", msg)
        # 微信ID
        username = msg.timelineObject.username
        # 头像路径
        avatar_path = self.avatar_exporter.get_avatar_path(username)
        contact = contacts_map.get(username)
        # 备注， 或用户名
        remark = contact.remark if contact.remark else contact.nickName
        # 朋友圈图片。实况短视频按下标跟在对应封面上。
        live_media = live_media_by_index(msg_dict)
        images = self.image_exporter.get_images(
            msg, live_media, self.video_exporter.save_live_video
        )
        self._remember_owner_images(username, images)
        # 朋友圈视频
        videos = self.video_exporter.get_videos(msg)
        # 样式   3:链接样式
        content_style = msg.timelineObject.ContentObject.contentStyle

        # 生成excel表格，导出朋友圈数据
        # 发布朋友圈的时间
        publish_time = msg.timelineObject.create_time
        # 发布朋友圈的文案
        publish_content = ""
        if msg.timelineObject.contentDesc:
            publish_content = msg.timelineObject.contentDesc
            publish_content = EmojiExporter.replace_emoji(publish_content)
        # 发布朋友的图片
        publish_images = ""
        live_paths = []
        if len(images) != 0:
            for _thumb_path, image_path, live_path in images:
                publish_images += str(image_path) + ";"
                if live_path:
                    live_paths.append(str(live_path))
        # 发布朋友的视频
        publish_videos = ""
        if len(videos) != 0:
            for video_path in videos:
                publish_videos = video_path
        if live_paths:
            joined = ";".join(live_paths)
            publish_videos = f"{publish_videos};{joined}" if publish_videos else joined
        # 发布朋友圈的位置，可能为空
        publish_poiName = ""
        if msg.timelineObject.location and msg.timelineObject.location.poiName:
            publish_poiName = msg.timelineObject.location.poiName
        # 将互动内容同时保存在 Excel 中，便于后续检索与整理。
        like_names: list[str] = []
        comment_texts: list[str] = []
        for interaction in comments:
            author_name = self._resolve_interaction_name(interaction.from_user_name)
            if interaction.is_like:
                if author_name not in like_names:
                    like_names.append(author_name)
            else:
                comment_text = interaction.content.replace("\r\n", "\n").replace("\r", "\n")
                reply_id = interaction.reply_user_name.strip()
                if reply_id:
                    reply_name = self._resolve_interaction_name(reply_id)
                    comment_texts.append(f"{author_name} 回复 {reply_name}：{comment_text}")
                else:
                    comment_texts.append(f"{author_name}：{comment_text}")

        # 添加数据到 Excel 表格中
        self.outws.append(
            [
                publish_time,
                username,
                remark,
                avatar_path,
                publish_content,
                publish_images,
                publish_videos,
                publish_poiName,
                "、".join(like_names),
                "\n".join(comment_texts),
            ]
        )
        fileName = "朋友圈数据.xlsx"
        filePath = os.path.join(self.output_folder, fileName)
        self.outwb.save(filePath)

        # 生成html
        html = ' <div class="row item">\n'
        html += '    <div class="col-xs-2">\n'
        html += '         <div class="logo01_box">\n'
        html += f'             <img src="{avatar_path}" />\n'
        html += "         </div>\n"
        html += "    </div>\n"
        html += '    <div class="col-xs-10 xs8">\n'
        html += '          <div class="towp">\n'
        html += f'              <p class="p1">{remark}</p>\n'
        if msg.timelineObject.contentDesc:
            content_desc = msg.timelineObject.contentDesc.replace("\n", "<br>")
            content_desc = EmojiExporter.replace_emoji(content_desc)
            html += f'              <p class="p2">{content_desc}</p>\n'
        html += "          </div>\n"

        # 超链接
        if content_style == 3:
            html += f'  <a href="{msg.timelineObject.ContentObject.contentUrl}" target="_blank">\n'
            html += '      <div class ="out_link" >\n'
            if images:
                _thumb_path, image_path, _live_path = images[0]
                html += f'        <img src="{image_path}"/>\n'
            html += f'       <div class ="text" >{msg.timelineObject.ContentObject.title}</div>\n'
            html += "      </div >\n"
            html += "   </a>\n"
        # 音乐
        elif is_music_msg(msg):

            title, musician, src = get_music_info(msg)
            html += f'  <a href="{msg.timelineObject.ContentObject.contentUrl}" target="_blank">\n'
            html += '      <div class ="music_link" >\n'
            html += '        <div class ="music_des" >\n'
            if images:
                thumb_path, _image_path, _live_path = images[0]
                html += f'        <img src = "{thumb_path}"/>\n'
            html += '             <div class = "music_title_musician">\n'
            html += f'               <div class = "music_title">{title}</div>\n'
            html += f'               <div class = "music_musician">{musician}</div>\n'
            html += "             </div>\n"
            html += "         </div>\n"
            html += f'        <audio class = "music_audio" controls>'
            html += f'             <source src="{src}" type="audio/mpeg">'
            html += f"        </audio>"
            html += "      </div >\n"
            html += "   </a>\n"
        # 视频号
        elif msg.timelineObject.ContentObject.finderFeed:
            html += f'     <div style="width:10rem; overflow:hidden">\n'
            # 视频号图片
            thumb_path = self.image_exporter.get_finder_images(msg)
            html += f"""       <img src=\"{thumb_path}\" onclick=\"openWarningOverlay(event)\" 
                               style=\"width:10rem;height:10rem;object-fit:cover;cursor:pointer;\"/>\n"""
            html += "      </div>\n"

            # 视频号说明
            html += '          <div class="texts_box">\n'
            nickname = msg.timelineObject.ContentObject.finderFeed.nickname
            desc = msg.timelineObject.ContentObject.finderFeed.desc
            html += (
                f'            <p class="location">视频号 · {nickname} · {desc}</p>\n'
            )
            html += "         </div>\n"
        # 普通朋友圈
        else:
            html += render_images_html(images)

            html += "      <div>\n"
            for video_path in videos:
                html += f'     <video controls height="500">\n'
                html += f'        <source src="{video_path}" type="video/mp4">\n'
                html += "     </video>\n"
            html += "      </div>\n"

        html += '          <div class="texts_box">\n'
        if msg.timelineObject.location and msg.timelineObject.location.poiName:
            html += f'        <p class="location">{msg.timelineObject.location.poiName}</p>\n'
        html += f'            <p class="time">{msg.timelineObject.create_time}</p>\n'
        html += "         </div>\n"
        # 互动信息沿用原模板的朋友圈卡片和 .pls 样式，只在原条目下方增加一块内容。
        html += render_interactions_html(
            comments,
            self._resolve_interaction_name,
            EmojiExporter.replace_emoji,
        )
        html += "    </div>\n"
        html += "</div>\n"
        self.file.write(html)

    def finish_file(self):
        self.file.write(self.html_end)
        self.file.close()
        html_path = Path(f"output/{self.dir_name}/index.html")
        text = html_path.read_text(encoding="utf-8")
        if "{cover_path}" in text:
            text = text.replace("{cover_path}", self._resolve_cover_path())
            html_path.write_text(text, encoding="utf-8")
