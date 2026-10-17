import os
from typing import Optional, Tuple

import requests
import uuid

from entity.moment_msg import MomentMsg
from exporter.isaac64 import Isaac64


class ImageExporter:
    def __init__(self, dir_name: str):
        self.dir_name = dir_name
        if not os.path.exists(f'output/{self.dir_name}/thumbs/'):
            os.mkdir(f'output/{self.dir_name}/thumbs/')
        if not os.path.exists(f'output/{self.dir_name}/images/'):
            os.mkdir(f'output/{self.dir_name}/images/')

    @staticmethod
    def _image_ext(data: bytes) -> Optional[str]:
        if data.startswith(b'\xff\xd8\xff'):
            return 'jpg'
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        if data.startswith((b'GIF87a', b'GIF89a')):
            return 'gif'
        if len(data) >= 12 and data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            return 'webp'
        return None

    @staticmethod
    def _restore_image(data: bytes, key: str) -> Optional[bytes]:
        if not data:
            return None
        if ImageExporter._image_ext(data):
            return data
        if not key or not str(key).isdigit():
            return None
        stream = Isaac64(int(key)).keystream(len(data))
        plain = (int.from_bytes(data, 'big') ^ int.from_bytes(stream, 'big')).to_bytes(len(data), 'big')
        if ImageExporter._image_ext(plain):
            return plain
        return None

    @staticmethod
    def get_image(link: tuple) -> Optional[bytes]:
        """ 向微信服务器请求图片，必要时按图片自带的密钥还原。
        """
        url = link[0] if link else ''
        idx = link[1] if len(link) > 1 else ''
        token = link[2] if len(link) > 2 else ''
        key = link[3] if len(link) > 3 else ''
        if not url:
            return None
        if idx and token:
            joiner = '&' if '?' in url else '?'
            url = f'{url}{joiner}idx={idx}&token={token}'
        try:
            session = requests.Session()
            session.trust_env = False
            response = session.get(
                url,
                timeout=20,
                headers={'User-Agent': 'MicroMessenger Client'},
            )
        except requests.RequestException:
            return None
        if not response.ok:
            return None
        return ImageExporter._restore_image(response.content, key)

    def _write_image(self, content: bytes, folder: str) -> Optional[str]:
        ext = self._image_ext(content)
        if not ext:
            return None
        file_name = uuid.uuid4()
        relative = f'{folder}/{file_name}.{ext}'
        with open(f'output/{self.dir_name}/{relative}', 'wb') as file:
            file.write(content)
        return relative

    def save_image(self, link: tuple, img_type: str) -> Optional[str]:
        """ 下载图片
        """
        if img_type not in ('image', 'thumb'):
            raise Exception("img_type 参数非法")
        content = self.get_image(link)
        if not content:
            return None
        folder = 'images' if img_type == 'image' else 'thumbs'
        return self._write_image(content, folder)

    @staticmethod
    def _media_link(media) -> Tuple:
        if isinstance(media, str):
            return (media, "", "", "")
        return (
            media.text or "",
            media.enc_idx or "",
            media.token or "",
            media.key or "",
        )

    @staticmethod
    def get_image_thumb_and_url(media_item, _content_style: int) -> Tuple[Optional[Tuple], Optional[Tuple]]:
        """ 获取图片的缩略图与大图的链接
        """
        thumb = None
        url = None
        # 普通图片，以及带封面的链接。链接帖继续用带 token 的原图地址。
        if media_item.type == "2" and media_item.url and media_item.thumb:
            thumb = ImageExporter._media_link(media_item.thumb)
            url = ImageExporter._media_link(media_item.url)
        # 微信音乐
        elif media_item.type == "5" and media_item.thumb:
            thumb = (media_item.thumb.text, "", "", "")
            url = (media_item.thumb.text, "", "", "")
        return thumb, url

    def get_images(self, msg: MomentMsg, live_media: Optional[list] = None, save_live=None) -> list[Tuple]:
        """ 获取一条朋友圈的全部图像。

        返回 [(缩略图路径, 原图路径, 实况视频路径或空字符串)]。
        live_media 与原始 media 列表等长，某一项有实况短视频时才下载。
        """
        results = []
        if not msg.timelineObject.ContentObject.mediaList:
            return results

        media = msg.timelineObject.ContentObject.mediaList.media
        for index, media_item in enumerate(media):
            thumb, url = self.get_image_thumb_and_url(
                media_item, msg.timelineObject.ContentObject.contentStyle
            )
            if not thumb or not url:
                continue
            image_content = self.get_image(url) or self.get_image(thumb)
            if not image_content:
                continue
            image_path = self._write_image(image_content, 'images')
            thumb_content = self.get_image(thumb) or image_content
            thumb_path = self._write_image(thumb_content, 'thumbs')
            if not thumb_path or not image_path:
                continue
            live_path = ""
            live_item = live_media[index] if live_media and index < len(live_media) else None
            if live_item and save_live:
                saved = save_live(live_item)
                if saved:
                    live_path = saved if str(saved).startswith("videos/") else f"videos/{saved}"
            results.append((thumb_path, image_path, live_path))

        return results

    def get_finder_images(self, msg: MomentMsg) -> Optional[str]:
        """ 获取视频号的封面图
        """
        results = None
        if not msg.timelineObject.ContentObject.finderFeed:
            return results

        if not msg.timelineObject.ContentObject.finderFeed.mediaList:
            return results

        media = msg.timelineObject.ContentObject.finderFeed.mediaList.media
        for media_item in media:
            thumb_path = self.save_image((media_item.thumbUrl, "", ""), 'thumb')
            return thumb_path
