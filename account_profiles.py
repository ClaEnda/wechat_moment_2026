# -*- coding: utf-8 -*-
"""本机多微信账号档案；敏感密钥使用 Windows DPAPI 保护，不以明文写入磁盘。"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
    buffer = ctypes.create_string_buffer(data)
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("密钥保护需要 Windows DPAPI")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    source, source_buffer = _blob(data)
    target = _DATA_BLOB()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "WechatMoments account secrets", None, None, None,
            0x1, ctypes.byref(target)
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)
        )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


class AccountProfileStore:
    """保存账号目录、wxid、显示名等元数据；密钥字段单独 DPAPI 加密。"""

    def __init__(self, root: str | None = None):
        base = root or os.environ.get("LOCALAPPDATA") or str(Path.home())
        self.root = Path(base) / "WechatMoments"
        self.profile_dir = self.root / "accounts"
        self.index_path = self.root / "accounts.json"
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def profile_id_for_path(account_dir: str) -> str:
        normalized = os.path.normcase(os.path.abspath(account_dir))
        digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return digest

    @staticmethod
    def safe_component(value: str, fallback: str = "account") -> str:
        value = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "")).strip("._-")
        return (value or fallback)[:48]

    def workspace_for(self, profile: dict) -> Path:
        profile_id = self.safe_component(profile.get("profile_id") or self.profile_id_for_path(profile.get("account_dir", "")))
        result = self.profile_dir / profile_id
        result.mkdir(parents=True, exist_ok=True)
        return result

    def load_profiles(self) -> list[dict]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("profile_id")]

    def save_profile(self, profile: dict) -> dict:
        item = {
            "profile_id": str(profile.get("profile_id") or self.profile_id_for_path(profile.get("account_dir", ""))),
            "wxid": str(profile.get("wxid") or ""),
            "display_name": str(profile.get("display_name") or ""),
            "account_dir": os.path.abspath(str(profile.get("account_dir") or "")),
            "db_storage": os.path.abspath(str(profile.get("db_storage") or "")),
            "weixin4": bool(profile.get("weixin4", True)),
            "process_ids": [int(pid) for pid in profile.get("process_ids", []) if str(pid).isdigit()],
            "last_used": int(profile.get("last_used") or 0),
        }
        profiles = {p["profile_id"]: p for p in self.load_profiles()}
        profiles[item["profile_id"]] = item
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.index_path.with_suffix(".tmp")
        temp.write_text(json.dumps(list(profiles.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.index_path)
        self.workspace_for(item)
        return item

    def delete_profile(self, profile_id: str) -> None:
        profiles = [p for p in self.load_profiles() if p.get("profile_id") != profile_id]
        if self.root.exists():
            self.index_path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        # 仅删除账号元数据和密钥，不自动删除数据库/媒体副本，避免误删备份。

    def save_secrets(self, profile_id: str, secrets: dict[str, str]) -> None:
        clean = {str(k): str(v) for k, v in secrets.items() if str(v).strip()}
        payload = json.dumps(clean, ensure_ascii=False).encode("utf-8")
        protected = _dpapi(payload, protect=True)
        destination = self.profile_dir / self.safe_component(profile_id) / "secrets.dpapi"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(".tmp")
        temp.write_bytes(base64.b64encode(protected))
        os.replace(temp, destination)

    def load_secrets(self, profile_id: str) -> dict[str, str]:
        source = self.profile_dir / self.safe_component(profile_id) / "secrets.dpapi"
        if not source.is_file():
            return {}
        try:
            encrypted = base64.b64decode(source.read_bytes(), validate=True)
            plain = _dpapi(encrypted, protect=False)
            data = json.loads(plain.decode("utf-8"))
            return {str(k): str(v) for k, v in data.items() if isinstance(v, (str, int))}
        except Exception:
            return {}

    def delete_secrets(self, profile_id: str) -> None:
        source = self.profile_dir / self.safe_component(profile_id) / "secrets.dpapi"
        try:
            source.unlink()
        except FileNotFoundError:
            pass
