import io
import os

from PIL import Image


class AvatarExporter:
    def __init__(self, dir_name: str):
        self.dir_name = dir_name
        # 已经写到磁盘的头像。Key: userName value: 相对路径
        self._saved_map = {}
        self._missing = set()
        if not os.path.exists(f'output/{self.dir_name}/avatars/'):
            os.mkdir(f'output/{self.dir_name}/avatars/')

    def get_avatar_path(self, userName) -> str:
        if not userName:
            return ""
        if userName in self._saved_map:
            return self._saved_map[userName]
        if userName in self._missing:
            return ""

        relative = self._save_bytes(self._avatar_bytes(userName), userName)
        if relative:
            self._saved_map[userName] = relative
            return relative
        self._missing.add(userName)
        return ""

    def _avatar_bytes(self, userName) -> bytes:
        from app.DataBase import misc_db

        blob_data = misc_db.get_avatar_buffer(userName)
        if blob_data:
            return blob_data
        from exporter.image_exporter import ImageExporter

        for url in self._head_urls(userName):
            content = ImageExporter.get_image((url, "", "", ""))
            if content:
                return content
        return b""

    @staticmethod
    def _head_urls(userName: str) -> list[str]:
        try:
            from app.DataBase import micro_msg_db

            info = micro_msg_db.get_contact_by_username(userName)
        except Exception:
            return []
        if not info:
            return []
        urls = []
        if len(info) > 8 and info[8]:
            urls.append(str(info[8]))
        if len(info) > 7 and info[7]:
            urls.append(str(info[7]))
        return urls

    def _save_bytes(self, data: bytes, userName: str) -> str:
        if not data:
            return ""
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception:
            return ""
        relative = f"avatars/{userName}.png"
        target = f"output/{self.dir_name}/{relative}"
        image.save(target, "PNG")
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return relative
        return ""
