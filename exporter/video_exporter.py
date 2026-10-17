import logging
import math
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional

import requests

from entity.moment_msg import Enc, Media, MomentMsg, Url
from exporter.isaac64 import Isaac64
from log import LOG


class VideoExporter:
    def __init__(self, dir_name, convert_video=0):
        self.dir_name = dir_name
        self.convert_video = bool(convert_video)
        if not os.path.exists(f'output/{self.dir_name}/videos/'):
            os.mkdir(f'output/{self.dir_name}/videos/')

    def find_video_by_md5(self, md5):
        """
        使用MD5匹配视频
        """
        folder_path = Path(f'output/{self.dir_name}/videos/')
        pattern = re.compile(r'^(.*?)(?=_)')

        for file_path in folder_path.iterdir():
            match = pattern.search(file_path.name)
            if match:
                filename_md5 = match.group()
                if filename_md5 == md5:
                    return file_path.name

    def find_video_by_duration(self, duration):
        """
        使用视频时长匹配视频
        """
        folder_path = Path(f'output/{self.dir_name}/videos/')
        pattern = re.compile(r'_([0-9.]+)\.mp4')

        for file_path in folder_path.iterdir():
            match = pattern.search(file_path.name)
            if match:
                filename_duration = float(match.group(1))
                if math.isclose(filename_duration, duration, abs_tol=0.005):
                    return file_path.name

    # 微信只加密视频开头的 128KB，后面的画面本来就是明文。
    _ENCRYPTED_PREFIX = 131072

    @staticmethod
    def _is_mp4(data: bytes) -> bool:
        return len(data) >= 12 and data[4:8] == b"ftyp"

    @staticmethod
    def _restore_video(data: bytes, key: str) -> Optional[bytes]:
        if VideoExporter._is_mp4(data):
            return data
        if not data or not key or not str(key).isdigit():
            return None
        prefix = min(len(data), VideoExporter._ENCRYPTED_PREFIX)
        stream = Isaac64(int(key)).keystream(prefix)
        plain = bytes(left ^ right for left, right in zip(data[:prefix], stream)) + data[prefix:]
        if VideoExporter._is_mp4(plain):
            return plain
        return None

    def _download_video(self, media_item: Media) -> Optional[str]:
        url = media_item.url
        link = url.text if isinstance(url, Url) else (url or "")
        link = str(link).strip()
        if not link:
            return None
        enc_key = media_item.enc.key if isinstance(media_item.enc, Enc) else ""
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        try:
            session = requests.Session()
            session.trust_env = False
            response = session.get(
                link,
                timeout=120,
                headers={"User-Agent": "MicroMessenger Client"},
            )
        except requests.RequestException:
            LOG.error("下载朋友圈视频失败")
            return None
        if not response.ok:
            LOG.error("下载朋友圈视频失败")
            return None
        content = self._restore_video(response.content, enc_key)
        if not content:
            LOG.error("还原朋友圈视频失败")
            return None
        file_name = f"{uuid.uuid4()}.mp4"
        path = Path(f"output/{self.dir_name}/videos/{file_name}")
        path.write_bytes(content)
        saved = self._transcode(path)
        return saved.name

    def _transcode(self, path: Path) -> Path:
        if not self.convert_video:
            return path
        from decrypter.video_decrypt import VideoDecrypter

        ffmpeg_path = VideoDecrypter.get_ffmpeg_path()
        if not os.path.exists(ffmpeg_path):
            return path
        temp_path = path.with_name(f"{path.stem}.h264.mp4")
        cmd = [
            ffmpeg_path,
            "-loglevel",
            "quiet",
            "-y",
            "-i",
            str(path),
            "-c:v",
            "libx264",
            str(temp_path),
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except OSError:
            return path
        if temp_path.is_file() and temp_path.stat().st_size > 0:
            path.unlink(missing_ok=True)
            temp_path.replace(path)
        elif temp_path.exists():
            temp_path.unlink()
        return path

    def _cached_video(self, media_item: Media) -> Optional[str]:
        url = media_item.url
        md5 = url.md5 if isinstance(url, Url) else ""
        if md5:
            cached = self.find_video_by_md5(md5)
            if cached:
                return cached
        if not media_item.videoDuration:
            return None
        try:
            rounded_duration = round(float(media_item.videoDuration), 2)
        except (TypeError, ValueError):
            return None
        return self.find_video_by_duration(rounded_duration)

    def save_live_video(self, media_item: Media) -> Optional[str]:
        """下载一条实况短视频，返回 videos 目录里的文件名。失败时返回 None。"""
        if media_item is None or str(media_item.type) != "6":
            return None
        url = media_item.url
        md5 = url.md5 if isinstance(url, Url) else ""
        if md5:
            cached = self.find_video_by_md5(md5)
            if cached:
                return cached
        return self._download_video(media_item)

    def get_videos(self, msg: MomentMsg) -> list[str]:
        """ 获取一条朋友圈的全部视频， 返回值是一个文件路径列表
        """
        results = []
        if not msg.timelineObject.ContentObject.mediaList:
            return results

        media = msg.timelineObject.ContentObject.mediaList.media
        for media_item in media:
            if media_item.type != "6":
                continue
            video = self._cached_video(media_item) or self._download_video(media_item)
            if video:
                results.append(f"videos/{video}")

        return results
