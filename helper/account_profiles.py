from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AccountProfileError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDpapi:
    """使用当前 Windows 用户的 DPAPI 保护本地密钥，不将密钥明文写入档案文件。"""

    @staticmethod
    def _api():
        if os.name != "nt":
            raise AccountProfileError("账号密钥保护功能仅支持 Windows")
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
            ctypes.wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        return crypt32, kernel32

    @classmethod
    def protect(cls, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise AccountProfileError("密钥不能为空")
        crypt32, kernel32 = cls._api()
        raw = value.encode("utf-8")
        source_buffer = ctypes.create_string_buffer(raw)
        source = _DataBlob(
            len(raw),
            ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        result = _DataBlob()
        if not crypt32.CryptProtectData(
            ctypes.byref(source), "WechatMoments account secret",
            None, None, None, 0, ctypes.byref(result)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            protected = ctypes.string_at(result.pbData, result.cbData)
            return base64.b64encode(protected).decode("ascii")
        finally:
            kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))

    @classmethod
    def unprotect(cls, value: str) -> str:
        crypt32, kernel32 = cls._api()
        try:
            raw = base64.b64decode(value, validate=True)
        except Exception as exc:
            raise AccountProfileError("账号密钥档案格式无效") from exc
        source_buffer = ctypes.create_string_buffer(raw)
        source = _DataBlob(
            len(raw),
            ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        result = _DataBlob()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(result.pbData, result.cbData).decode("utf-8")
        finally:
            kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


class AccountProfileStore:
    """保存多开微信账号档案；账号元数据为 JSON，密钥字段单独使用 DPAPI 加密。"""

    SECRET_FIELDS = {
        "legacy_db_key",
        "sns_db_key",
        "contact_db_key",
        "image_key",
    }
    WXID_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")

    def __init__(self, path: str | None = None, protector: Any = WindowsDpapi):
        if path is None:
            path = os.path.join(str(portable_root()), "app", "KeyVault", "accounts.json")
        self.path = Path(path)
        self.protector = protector
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "profiles": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AccountProfileError(f"无法读取账号档案：{exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
            raise AccountProfileError("账号档案文件结构无效")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="accounts-", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @classmethod
    def _validate_profile(cls, profile: dict[str, Any]) -> dict[str, Any]:
        wxid = str(profile.get("wxid") or "").strip()
        if not cls.WXID_PATTERN.fullmatch(wxid):
            raise AccountProfileError("wxid 不能为空，且只能包含字母、数字、下划线、点、@ 或连字符")
        version = str(profile.get("wechat_version") or "4.x").strip()
        if version not in {"3.x", "4.x"}:
            raise AccountProfileError("微信版本只支持 3.x 或 4.x")
        account_dir = os.path.abspath(os.path.expandvars(os.path.expanduser(str(profile.get("account_dir") or ""))))
        if not os.path.isdir(account_dir):
            raise AccountProfileError("账号数据目录不存在，请确认目录映射")
        db_storage = str(profile.get("db_storage") or "").strip()
        if version == "4.x":
            if not db_storage:
                db_storage = os.path.join(account_dir, "db_storage")
            db_storage = os.path.abspath(os.path.expandvars(os.path.expanduser(db_storage)))
            if not os.path.isdir(db_storage):
                raise AccountProfileError("微信 4.x 的 db_storage 目录不存在")
        else:
            db_storage = ""
            if not os.path.isdir(os.path.join(account_dir, "Msg")):
                raise AccountProfileError("微信 3.x 账号目录中没有 Msg 子目录，请重新选择 WeChat Files/wxid_* 目录")
        display_name = str(profile.get("display_name") or "").strip()[:80]
        process_ids = []
        for item in profile.get("process_ids") or []:
            try:
                pid = int(item)
            except (TypeError, ValueError):
                continue
            if pid > 0 and pid not in process_ids:
                process_ids.append(pid)
        return {
            "wxid": wxid,
            "display_name": display_name or wxid,
            "wechat_version": version,
            "account_dir": account_dir,
            "db_storage": db_storage,
            "process_ids": process_ids,
            "created_at": str(profile.get("created_at") or datetime.now(timezone.utc).isoformat()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save_profile(self, profile: dict[str, Any], secrets: dict[str, str] | None = None) -> None:
        clean = self._validate_profile(profile)
        secrets = secrets or {}
        unknown = set(secrets) - self.SECRET_FIELDS
        if unknown:
            raise AccountProfileError("未知密钥字段：" + ", ".join(sorted(unknown)))
        protected = {}
        for field, value in secrets.items():
            if value is None or str(value) == "":
                continue
            protected[field] = self.protector.protect(str(value))
        data = self._read()
        old = data["profiles"].get(clean["wxid"], {})
        if old.get("created_at"):
            clean["created_at"] = old["created_at"]
        old_secrets = old.get("protected_secrets", {})
        old_secrets.update(protected)
        clean["protected_secrets"] = old_secrets
        data["profiles"][clean["wxid"]] = clean
        self._write(data)

    def list_profiles(self) -> list[dict[str, Any]]:
        data = self._read()
        result = []
        for value in data["profiles"].values():
            result.append({k: v for k, v in value.items() if k != "protected_secrets"})
        return sorted(result, key=lambda item: (item.get("display_name", "").casefold(), item["wxid"]))

    def get_profile(self, wxid: str) -> dict[str, Any] | None:
        data = self._read()
        value = data["profiles"].get(wxid)
        if not value:
            return None
        return {k: v for k, v in value.items() if k != "protected_secrets"}

    def get_secrets(self, wxid: str) -> dict[str, str]:
        data = self._read()
        value = data["profiles"].get(wxid)
        if not value:
            raise AccountProfileError(f"找不到账号档案：{wxid}")
        protected = value.get("protected_secrets", {})
        result = {}
        for field, secret in protected.items():
            result[field] = self.protector.unprotect(secret)
        return result

    def remove_profile(self, wxid: str) -> bool:
        data = self._read()
        if wxid not in data["profiles"]:
            return False
        del data["profiles"][wxid]
        self._write(data)
        return True


def profile_cache_dir(wxid: str, root: str | None = None) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(wxid))
    if not safe:
        raise AccountProfileError("wxid 无效，无法建立独立缓存目录")
    if root is None:
        root = os.path.join(str(portable_root()), "app", "DataBase", "Accounts")
    path = os.path.abspath(os.path.join(root, safe))
    os.makedirs(path, exist_ok=True)
    return path


def portable_root() -> Path:
    """返回便携程序根目录；开发运行时返回项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
