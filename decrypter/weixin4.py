"""读取本机已登录微信 4.x 的朋友圈库和联系人库。

密钥只在进程内存里用于校验和解密，不写入日志、界面或文件。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import glob
import hashlib
import hmac
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import winreg
from helper.db_snapshot import copy_sqlite_snapshot
from xml.etree import ElementTree

PAGE_SZ = 4096
KEY_SZ = 32
SALT_SZ = 16
IV_SZ = 16
HMAC_SZ = 64
RESERVE_SZ = 80
SQLITE_HDR = b"SQLite format 3\x00"
CONFIG_CIPHER_NAME = b"com.Tencent.WCDB.Config.Cipher"
CONFIG_XOR_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b"
    "450048844c2448488944254048584c24"
)
CONFIG_LITERAL_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")
HEX_RE = re.compile(rb"x'([0-9a-fA-F]{64,192})'")
MAX_USER_ADDRESS = 0x0000800000000000
CONFIG_BLOB_MAX = 1024
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}
MEM_COMMIT = 0x1000
CREATE_TIME_RE = re.compile(r"""createTime(?:=\"|>)(\d+)""")

_bcrypt = ctypes.WinDLL("bcrypt")
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_bcrypt.BCryptOpenAlgorithmProvider.argtypes = [
    ctypes.POINTER(wt.HANDLE), ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong,
]
_bcrypt.BCryptSetProperty.argtypes = [
    wt.HANDLE, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
]
_bcrypt.BCryptGenerateSymmetricKey.argtypes = [
    wt.HANDLE, ctypes.POINTER(wt.HANDLE), ctypes.c_void_p, ctypes.c_ulong,
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
]
_bcrypt.BCryptDecrypt.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong,
]
_kernel32.OpenProcess.restype = ctypes.c_void_p
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.ReadProcessMemory.restype = wt.BOOL
_kernel32.ReadProcessMemory.argtypes = [
    ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
_kernel32.VirtualQueryEx.restype = ctypes.c_size_t
_kernel32.VirtualQueryEx.argtypes = [
    ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t,
]
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]


class MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD),
        ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("_pad2", wt.DWORD),
    ]


class Weixin4Error(RuntimeError):
    pass


def probe_client() -> dict:
    """判断当前是微信 4.x、缺少数据目录，还是可以继续走旧版检测。"""
    if not _weixin_pids():
        return {"state": "absent"}
    account_dir, db_storage = _locate_account()
    if not account_dir:
        return {
            "state": "weixin4-error",
            "message": "已发现微信 4.1，但没有找到本地数据库目录",
        }
    return {
        "state": "weixin4",
        "account": {
            "weixin4": True,
            "filePath": account_dir,
            "dbStorage": db_storage,
            "key": "",
            "wxid": "",
        },
    }


def build_export_databases(account_info: dict, progress) -> None:
    """解密朋友圈和联系人库，并写成现有导出器使用的表。"""
    accounts = _iter_accounts()
    pages = []
    for _account_dir, storage in accounts:
        for rel in (os.path.join("sns", "sns.db"), os.path.join("contact", "contact.db")):
            path = os.path.join(storage, rel)
            if os.path.isfile(path) and os.path.getsize(path) >= PAGE_SZ:
                pages.append(path)
    if not pages:
        raise Weixin4Error("没有找到朋友圈或联系人数据库")

    progress(5, "正在读取已登录的微信....")
    path_keys, stats = _extract_keys(pages, progress)
    chosen = None
    for account_dir, storage in accounts:
        sns_path = os.path.join(storage, "sns", "sns.db")
        contact_path = os.path.join(storage, "contact", "contact.db")
        if path_keys.get(sns_path) and path_keys.get(contact_path):
            chosen = (account_dir, storage, sns_path, contact_path)
            break
    if not chosen:
        raise Weixin4Error(
            "未能校验微信 4.1 的本地数据库。请保持微信登录，并尝试用管理员身份重新打开本工具。"
            f"（内存区域 {stats['regions']}，特征 {stats['needles']}，候选 {stats['candidates']}，"
            f"已匹配 {stats['matched']}）"
        )
    account_dir, storage, sns_path, contact_path = chosen
    account_info["filePath"] = account_dir
    account_info["dbStorage"] = storage
    key_map = {"sns": path_keys[sns_path], "contact": path_keys[contact_path]}

    work = tempfile.mkdtemp(prefix="weixin4-")
    try:
        decrypted = {}
        sources = {"sns": sns_path, "contact": contact_path}
        for index, name in enumerate(("sns", "contact")):
            progress(45 + index * 15, "正在复制本地数据库....")
            src = sources[name]
            copied = os.path.join(work, name + ".db")
            _copy_shared(src, copied)
            out_path = os.path.join(work, name + "-plain.db")
            if not _decrypt_database(copied, out_path, key_map[name]):
                raise Weixin4Error("本地数据库校验失败")
            wal = src + "-wal"
            if os.path.isfile(wal):
                _apply_wal(wal, out_path, key_map[name])
            if not _quick_check(out_path):
                raise Weixin4Error("解密后的数据库无法打开")
            decrypted[name] = out_path
            progress(60 + index * 15, "正在整理朋友圈数据....")
        output_dir = os.path.join("app", "DataBase", "Msg")
        os.makedirs(output_dir, exist_ok=True)
        wxid = _write_compatible(decrypted["sns"], decrypted["contact"], output_dir, account_dir)
        account_info["wxid"] = wxid
        progress(100, "复制成功，请点击下一步")
    finally:
        key_map.clear()
        path_keys.clear()
        shutil.rmtree(work, ignore_errors=True)


def build_export_databases_with_manual_keys(
    account_info: dict,
    db_keys: dict[str, str],
    profile_cache_dir: str,
    progress,
) -> None:
    """
    使用用户为该账号明确提供的数据库密钥，解密到该 wxid 独立缓存。

    本函数不枚举进程、不读取进程内存，也不自行寻找或导出任何密钥。
    """
    account_dir = os.path.abspath(str(account_info.get("filePath") or ""))
    storage = str(account_info.get("dbStorage") or "").strip()
    if not account_dir or not os.path.isdir(account_dir):
        raise Weixin4Error("账号数据目录不存在，请重新选择该微信实例对应的目录")
    if not storage:
        storage = os.path.join(account_dir, "db_storage")
    storage = os.path.abspath(storage)
    if not os.path.isdir(storage):
        raise Weixin4Error("没有找到该账号的 db_storage 目录")

    def parse_key(name: str) -> bytes:
        value = str(db_keys.get(name) or "").strip().replace(" ", "")
        try:
            key = bytes.fromhex(value)
        except ValueError as exc:
            raise Weixin4Error(f"{name} 必须是 64 位十六进制数据库密钥") from exc
        if len(key) != KEY_SZ:
            raise Weixin4Error(f"{name} 必须是 32 字节（64 位十六进制）数据库密钥")
        return key

    keys = {
        "sns": parse_key("sns_db_key"),
        "contact": parse_key("contact_db_key"),
    }
    os.makedirs(profile_cache_dir, exist_ok=True)
    source_cache = os.path.join(profile_cache_dir, "encrypted_source")
    plain_cache = os.path.join(profile_cache_dir, "database")
    os.makedirs(source_cache, exist_ok=True)
    os.makedirs(plain_cache, exist_ok=True)

    sources = {
        "sns": os.path.join(storage, "sns", "sns.db"),
        "contact": os.path.join(storage, "contact", "contact.db"),
    }
    decrypted = {}
    for index, name in enumerate(("sns", "contact")):
        src = sources[name]
        if not os.path.isfile(src):
            raise Weixin4Error(f"该账号缺少 {name} 数据库：{src}")

        progress(10 + index * 30, f"正在复制所选账号的 {name} 数据库....")
        snapshot = os.path.join(source_cache, name + ".db")
        try:
            copy_sqlite_snapshot(src, snapshot, retries=3)
        except Exception as exc:
            raise Weixin4Error(f"{name} 数据库正在变化，无法取得稳定快照：{exc}") from exc

        plain_path = os.path.join(plain_cache, name + "-plain.db")
        if os.path.exists(plain_path):
            os.remove(plain_path)
        if not _decrypt_database(snapshot, plain_path, keys[name]):
            raise Weixin4Error(f"{name} 数据库密钥与所选账号不匹配")
        if os.path.isfile(wal_snapshot):
            _apply_wal(wal_snapshot, plain_path, keys[name])
        if not _quick_check(plain_path):
            raise Weixin4Error(f"{name} 解密后的数据库检查失败")
        decrypted[name] = plain_path
        progress(35 + index * 25, f"{name} 数据库已校验")

    inferred_wxid = _write_compatible(
        decrypted["sns"],
        decrypted["contact"],
        plain_cache,
        account_dir,
    )
    # 档案中经用户确认的 wxid 是账号缓存隔离的主键，不用目录名推断值覆盖。
    if not account_info.get("wxid") and inferred_wxid:
        account_info["wxid"] = inferred_wxid
    account_info["dbStorage"] = storage
    account_info["databaseDir"] = plain_cache
    progress(100, "该账号的数据已复制并整理到独立缓存")


def _weixin_pids() -> list[int]:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    ranked = []
    for line in result.stdout.splitlines():
        if "Weixin.exe" not in line:
            continue
        parts = line.strip().strip('"').split('","')
        if len(parts) < 5 or not parts[1].isdigit():
            continue
        mem_text = parts[4].replace(",", "").replace("K", "").strip()
        mem = int(mem_text) if mem_text.isdigit() else 0
        ranked.append((mem, int(parts[1])))
    ranked.sort(reverse=True)
    return [pid for _mem, pid in ranked]


def _locate_account() -> tuple[str, str]:
    accounts = _iter_accounts()
    if not accounts:
        return "", ""
    return accounts[0]


def _iter_accounts() -> list[tuple[str, str]]:
    roots = []
    for path in _registry_values() + _ini_roots():
        if path and path not in roots:
            roots.append(path)
    home = os.path.expanduser("~")
    roots.extend([
        os.path.join(home, "Documents"),
        os.path.join(home, "Documents", "xwechat_files"),
        r"D:\xwechat_files",
        r"D:\\",
    ])
    candidates = []
    seen = set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        storage_dirs = []
        if os.path.basename(root).lower() == "xwechat_files":
            storage_dirs.extend(glob.glob(os.path.join(root, "*", "db_storage")))
        storage_dirs.extend(glob.glob(os.path.join(root, "xwechat_files", "*", "db_storage")))
        for storage in storage_dirs:
            storage = os.path.normpath(storage)
            if storage in seen or not os.path.isdir(storage):
                continue
            seen.add(storage)
            sns = os.path.join(storage, "sns", "sns.db")
            if os.path.isfile(sns):
                session = os.path.join(storage, "session", "session.db")
                stamp = os.path.getmtime(session) if os.path.isfile(session) else os.path.getmtime(sns)
                candidates.append((stamp, os.path.dirname(storage), storage))
    candidates.sort(reverse=True)
    return [(account_dir, storage) for _stamp, account_dir, storage in candidates]


def _registry_values() -> list[str]:
    values = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Tencent\Weixin") as key:
            for name in ("FileSavePath", "OldFileSavePath"):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if isinstance(value, str) and value:
                    values.append(value)
    except OSError:
        pass
    return values


def _ini_roots() -> list[str]:
    config_dir = os.path.join(os.environ.get("APPDATA", ""), "Tencent", "xwechat", "config")
    roots = []
    if not os.path.isdir(config_dir):
        return roots
    for ini_file in glob.glob(os.path.join(config_dir, "*.ini")):
        for encoding in ("utf-8", "gbk"):
            try:
                with open(ini_file, "r", encoding=encoding) as handle:
                    content = handle.read(1024).strip()
            except (OSError, UnicodeError):
                continue
            if content and os.path.isdir(content):
                roots.append(content)
            break
    return roots


def _copy_shared(src: str, dst: str) -> None:
    try:
        with open(src, "rb") as fin, open(dst, "wb") as fout:
            shutil.copyfileobj(fin, fout, length=1024 * 1024)
    except OSError as exc:
        raise Weixin4Error("无法复制数据库，请保持微信登录后重试") from exc


def _extract_keys(paths: list[str], progress) -> tuple[dict[str, bytes], dict]:
    files = []
    salt_to_paths: dict[str, list[str]] = {}
    for path in paths:
        with open(path, "rb") as handle:
            page1 = handle.read(PAGE_SZ)
        if len(page1) < PAGE_SZ:
            continue
        salt = page1[:SALT_SZ].hex()
        files.append((path, salt, page1))
        salt_to_paths.setdefault(salt, []).append(path)
    key_by_salt: dict[str, bytes] = {}
    remaining = set(salt_to_paths)
    stats = {"needles": 0, "candidates": 0, "regions": 0, "matched": 0}
    pids = _weixin_pids()
    opened = False
    for pid in pids:
        handle = _kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not handle:
            continue
        opened = True
        try:
            regions = _enum_regions(handle)
            stats["regions"] += len(regions)
            progress(15, "正在读取已登录的微信....")
            _scan_config_cipher(handle, regions, files, key_by_salt, remaining, progress, stats)
            if remaining:
                progress(35, "正在读取已登录的微信....")
                _scan_legacy_keys(handle, regions, files, key_by_salt, remaining, stats)
        finally:
            _kernel32.CloseHandle(handle)
        if not remaining:
            break
    if not opened:
        raise Weixin4Error("无法读取微信进程。请用管理员身份重新打开本工具，并保持微信登录。")
    stats["matched"] = len(key_by_salt)
    resolved = {}
    for salt, salt_paths in salt_to_paths.items():
        key = key_by_salt.get(salt)
        if not key:
            continue
        for path in salt_paths:
            resolved[path] = key
    return resolved, stats


def _enum_regions(handle) -> list[tuple[int, int]]:
    regions = []
    address = 0
    info = MemoryBasicInformation()
    while address < 0x7FFFFFFFFFFF:
        if _kernel32.VirtualQueryEx(handle, address, ctypes.byref(info), ctypes.sizeof(info)) == 0:
            break
        if info.State == MEM_COMMIT and info.Protect in READABLE and 0 < info.RegionSize < 500 * 1024 * 1024:
            regions.append((info.BaseAddress, info.RegionSize))
        nxt = info.BaseAddress + info.RegionSize
        if nxt <= address:
            break
        address = nxt
    return regions


def _read_mem(handle, address: int, size: int) -> bytes | None:
    if size <= 0:
        return None
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    if not _kernel32.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(read)):
        return None
    return buffer.raw[:read.value]


def _iter_chunks(handle, regions, overlap: int = 0, progress=None, start: int = 15, end: int = 34):
    total = max(1, len(regions))
    for index, (base, size) in enumerate(regions):
        if progress and index % 30 == 0:
            progress(start + int((end - start) * index / total), "正在读取已登录的微信....")
        offset = 0
        tail = b""
        tail_base = base
        while offset < size:
            current = min(2 * 1024 * 1024, size - offset)
            chunk = _read_mem(handle, base + offset, current) or b""
            data_base = tail_base if tail else base + offset
            data = tail + chunk
            if data:
                yield data_base, data
            if overlap and data:
                tail = data[-overlap:]
                tail_base = data_base + max(0, len(data) - len(tail))
            else:
                tail = b""
                tail_base = base + offset + current
            offset += current


def _scan_config_cipher(handle, regions, files, key_by_salt, remaining, progress, stats) -> None:
    needle_addresses = set()
    overlap = max(0, len(CONFIG_CIPHER_NAME) - 1)
    for data_base, data in _iter_chunks(handle, regions, overlap=overlap, progress=progress, start=15, end=28):
        pos = data.find(CONFIG_CIPHER_NAME)
        while pos >= 0:
            needle_addresses.add(data_base + pos)
            pos = data.find(CONFIG_CIPHER_NAME, pos + 1)
    stats["needles"] += len(needle_addresses)
    if not needle_addresses or not remaining:
        return
    patterns = [
        struct.pack("<Q", addr) + struct.pack("<Q", len(CONFIG_CIPHER_NAME))
        for addr in needle_addresses
    ]
    seen = set()
    for base, data in _iter_chunks(handle, regions, overlap=0x80, progress=progress, start=28, end=40):
        if not remaining:
            return
        for pattern in patterns:
            pos = data.find(pattern)
            while pos >= 0:
                _consider_config_node(
                    handle, base + pos, needle_addresses, files, key_by_salt, remaining, seen, stats,
                )
                pos = data.find(pattern, pos + 1)


def _consider_config_node(handle, qaddr, needle_addresses, files, key_by_salt, remaining, seen, stats) -> None:
    node = _read_mem(handle, qaddr - 0x10, 0x50)
    if not node or len(node) < 0x40:
        return
    if _u64(node, 0x10) not in needle_addresses or _u64(node, 0x18) != len(CONFIG_CIPHER_NAME):
        return
    config_ptr = _u64(node, 0x28)
    if not (0x10000 <= config_ptr < MAX_USER_ADDRESS):
        return
    obj = _read_mem(handle, config_ptr + 0x88, 0x28)
    if not obj or len(obj) < 0x18:
        return
    data_ptr = _u64(obj, 0x08)
    data_len = _u64(obj, 0x10)
    if not (0 < data_len <= CONFIG_BLOB_MAX and 0x10000 <= data_ptr < MAX_USER_ADDRESS):
        return
    blob = _read_mem(handle, data_ptr, int(data_len))
    if not blob or len(blob) != data_len:
        return
    for enc_key, embedded_salt in _config_key_candidates(blob):
        item = (enc_key.hex(), embedded_salt)
        if item in seen:
            continue
        seen.add(item)
        stats["candidates"] += 1
        _verify_candidate(enc_key, embedded_salt, files, key_by_salt, remaining)


def _config_key_candidates(blob: bytes) -> list[tuple[bytes, str | None]]:
    decoded = bytes(value ^ CONFIG_XOR_MASK[index % len(CONFIG_XOR_MASK)] for index, value in enumerate(blob))
    found = []
    seen = set()
    for match in CONFIG_LITERAL_RE.finditer(decoded):
        run = match.group(1).decode("ascii").lower()
        starts = [0]
        if len(run) > 96:
            starts.extend(range(0, len(run) - 63, 32))
            starts.append(len(run) - 64)
        for start in dict.fromkeys(starts):
            if start < 0 or start + 64 > len(run):
                continue
            try:
                enc_key = bytes.fromhex(run[start:start + 64])
            except ValueError:
                continue
            if not _probable_key(enc_key):
                continue
            embedded = run[start + 64:start + 96] if start + 96 <= len(run) else None
            item = (enc_key, embedded)
            if item not in seen:
                seen.add(item)
                found.append(item)
    return found


def _scan_legacy_keys(handle, regions, files, key_by_salt, remaining, stats) -> None:
    for _base, data in _iter_chunks(handle, regions, overlap=200):
        if not remaining:
            return
        for match in HEX_RE.finditer(data):
            hex_str = match.group(1).decode()
            if len(hex_str) < 96:
                continue
            try:
                enc_key = bytes.fromhex(hex_str[:64])
            except ValueError:
                continue
            stats["candidates"] += 1
            _verify_candidate(enc_key, hex_str[64:96], files, key_by_salt, remaining)


def _verify_candidate(enc_key: bytes, embedded_salt: str | None, files, key_by_salt, remaining) -> None:
    if not remaining or not _probable_key(enc_key):
        return
    salts = [embedded_salt] if embedded_salt in remaining else list(remaining)
    for salt in salts:
        if salt not in remaining:
            continue
        for _name, file_salt, page1 in files:
            if file_salt == salt and verify_enc_key(enc_key, page1):
                key_by_salt[salt] = enc_key
                remaining.discard(salt)
                break


def _probable_key(data: bytes) -> bool:
    return len(data) == KEY_SZ and len(set(data)) >= 15 and data not in {b"\x00" * KEY_SZ, b"\xff" * KEY_SZ}


def _u64(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 8 > len(data):
        return 0
    return struct.unpack_from("<Q", data, offset)[0]


def verify_enc_key(enc_key: bytes, page1: bytes) -> bool:
    salt = page1[:SALT_SZ]
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, bytes(b ^ 0x3A for b in salt), 2, dklen=KEY_SZ)
    digest = hmac.new(mac_key, page1[SALT_SZ:PAGE_SZ - RESERVE_SZ + IV_SZ], hashlib.sha512)
    digest.update(struct.pack("<I", 1))
    return digest.digest() == page1[PAGE_SZ - HMAC_SZ:PAGE_SZ]


def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    algorithm = wt.HANDLE()
    status = _bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), "AES", None, 0)
    if status != 0:
        raise Weixin4Error("系统解密组件不可用")
    try:
        mode = ctypes.create_string_buffer("ChainingModeCBC\x00".encode("utf-16-le"))
        status = _bcrypt.BCryptSetProperty(algorithm, "ChainingMode", mode, len(mode) - 1, 0)
        if status != 0:
            raise Weixin4Error("系统解密组件不可用")
        key_buf = ctypes.create_string_buffer(key, len(key))
        key_handle = wt.HANDLE()
        status = _bcrypt.BCryptGenerateSymmetricKey(
            algorithm, ctypes.byref(key_handle), None, 0, key_buf, len(key), 0,
        )
        if status != 0:
            raise Weixin4Error("系统解密组件不可用")
        try:
            iv_buf = ctypes.create_string_buffer(iv, len(iv))
            data_buf = ctypes.create_string_buffer(data, len(data))
            out_buf = ctypes.create_string_buffer(len(data))
            result_len = ctypes.c_ulong(0)
            status = _bcrypt.BCryptDecrypt(
                key_handle, data_buf, len(data), None,
                iv_buf, len(iv), out_buf, len(out_buf), ctypes.byref(result_len), 0,
            )
            if status != 0:
                raise Weixin4Error("数据库页解密失败")
            return out_buf.raw[:result_len.value]
        finally:
            _bcrypt.BCryptDestroyKey(key_handle)
    finally:
        _bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)


def _decrypt_page(enc_key: bytes, page: bytes, page_no: int) -> bytes:
    iv = page[PAGE_SZ - RESERVE_SZ:PAGE_SZ - RESERVE_SZ + IV_SZ]
    if page_no == 1:
        body = _aes_cbc_decrypt(enc_key, iv, page[SALT_SZ:PAGE_SZ - RESERVE_SZ])
        return SQLITE_HDR + body + b"\x00" * RESERVE_SZ
    body = _aes_cbc_decrypt(enc_key, iv, page[:PAGE_SZ - RESERVE_SZ])
    return body + b"\x00" * RESERVE_SZ


def _decrypt_database(src: str, dst: str, enc_key: bytes) -> bool:
    file_size = os.path.getsize(src)
    with open(src, "rb") as fin:
        page1 = fin.read(PAGE_SZ)
    if len(page1) < PAGE_SZ or not verify_enc_key(enc_key, page1):
        return False
    total_pages = file_size // PAGE_SZ
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        for page_no in range(1, total_pages + 1):
            page = fin.read(PAGE_SZ)
            if len(page) < PAGE_SZ:
                break
            fout.write(_decrypt_page(enc_key, page, page_no))
    return True


def _apply_wal(wal_path: str, db_path: str, enc_key: bytes) -> None:
    try:
        with open(wal_path, "rb") as handle:
            wal = handle.read()
    except OSError:
        return
    if len(wal) < 32 or wal[:4] not in (b"\x37\x7f\x06\x82", b"\x37\x7f\x06\x83"):
        return
    if int.from_bytes(wal[8:12], "big") != PAGE_SZ:
        return
    header_salt = wal[16:24]
    frame_size = 24 + PAGE_SZ
    matched = []
    others = []
    offset = 32
    while offset + frame_size <= len(wal):
        page_no = int.from_bytes(wal[offset:offset + 4], "big")
        frame_salt = wal[offset + 8:offset + 16]
        page = wal[offset + 24:offset + 24 + PAGE_SZ]
        if page_no > 0:
            item = (page_no, page)
            if frame_salt == header_salt:
                matched.append(item)
            else:
                others.append(item)
        offset += frame_size
    if not matched and not others:
        return
    original = open(db_path, "rb").read()
    chosen = matched or others
    if not _write_wal_pages(db_path, original, chosen, enc_key):
        if matched and others and not _write_wal_pages(db_path, original, matched + others, enc_key):
            with open(db_path, "wb") as handle:
                handle.write(original)


def _write_wal_pages(db_path: str, original: bytes, frames, enc_key: bytes) -> bool:
    data = bytearray(original)
    try:
        for page_no, page in frames:
            if len(page) != PAGE_SZ or page_no > 200000:
                continue
            plain = _decrypt_page(enc_key, page, page_no)
            start = (page_no - 1) * PAGE_SZ
            end = start + PAGE_SZ
            if end > len(data):
                data.extend(b"\x00" * (end - len(data)))
            data[start:end] = plain
    except Weixin4Error:
        with open(db_path, "wb") as handle:
            handle.write(original)
        return False
    with open(db_path, "wb") as handle:
        handle.write(data)
    if _quick_check(db_path):
        return True
    with open(db_path, "wb") as handle:
        handle.write(original)
    return False


def _quick_check(path: str) -> bool:
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("PRAGMA quick_check").fetchone()
        conn.close()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] == "ok"


def _write_compatible(sns_path: str, contact_path: str, output_dir: str, account_dir: str) -> str:
    sns = sqlite3.connect(sns_path)
    contact = sqlite3.connect(contact_path)
    try:
        feeds, comments = _read_moments(sns)
        people, self_name = _read_contacts(contact, account_dir)
    finally:
        sns.close()
        contact.close()
    if not feeds:
        raise Weixin4Error("朋友圈数据库里没有可导出的记录")
    _write_sns(os.path.join(output_dir, "Sns.db"), feeds, comments)
    _write_contacts(os.path.join(output_dir, "MicroMsg.db"), people)
    _write_empty_msg(os.path.join(output_dir, "MSG.db"))
    return self_name


def _read_moments(conn: sqlite3.Connection) -> tuple[list[tuple], list[tuple]]:
    tables = _table_names(conn)
    timeline = "SnsTimeLine" if "SnsTimeLine" in tables else ""
    if not timeline:
        raise Weixin4Error("朋友圈数据库结构无法识别：" + ", ".join(tables[:12]))
    columns = _column_names(conn, timeline)
    user_col = _pick(columns, "user_name", "username", "UserName")
    content_col = _pick(columns, "content", "Content")
    feed_col = _pick(columns, "tid", "feed_id", "FeedId", "id")
    time_col = _pick(columns, "create_time", "CreateTime")
    if not user_col or not content_col or not feed_col:
        raise Weixin4Error("朋友圈字段无法识别：" + ", ".join(columns[:12]))
    feeds = []
    selected = ", ".join(f'"{name}"' for name in (user_col, content_col, feed_col) + ((time_col,) if time_col else ()))
    for row in conn.execute(f'SELECT {selected} FROM "{timeline}"'):
        username = _as_text(row[0]).strip()
        content = _timeline_xml(_as_text(row[1]).strip())
        if not username or "TimelineObject" not in content:
            continue
        feed_id = _as_int(row[2])
        create_time = _as_int(row[3]) if time_col else 0
        if create_time <= 0:
            create_time = _create_time_from_xml(content)
        if create_time > 10**12:
            create_time //= 1000
        feeds.append((username, content, feed_id, create_time))
    comments = []
    if "SnsMessage_tmp3" in tables:
        comment_columns = _column_names(conn, "SnsMessage_tmp3")
        feed_id_col = _pick(comment_columns, "feed_id", "FeedId", "tid")
        from_col = _pick(comment_columns, "from_username", "FromUserName")
        type_col = _pick(comment_columns, "type", "CommentType")
        text_col = _pick(comment_columns, "content", "Content")
        ctime_col = _pick(comment_columns, "create_time", "CreateTime")
        if feed_id_col and from_col and type_col and text_col:
            comment_id_col = _pick(comment_columns, "comment_id", "CommentId")
            reply_user_col = _pick(comment_columns, "reply_username", "ReplyUserName")
            reply_id_col = _pick(comment_columns, "reply_id", "ReplyId")
            chosen = [feed_id_col, from_col, type_col, text_col]
            optional = [ctime_col, comment_id_col, reply_user_col, reply_id_col]
            chosen.extend(name for name in optional if name)
            sql = "SELECT " + ", ".join(f'"{name}"' for name in chosen) + ' FROM "SnsMessage_tmp3"'
            positions = {name: index for index, name in enumerate(chosen)}
            for row in conn.execute(sql):
                comments.append((
                    _as_text(row[positions[from_col]]),
                    _as_int(row[positions[type_col]]),
                    _as_text(row[positions[text_col]]),
                    _as_int(row[positions[feed_id_col]]),
                    _as_int(row[positions[ctime_col]]) if ctime_col else 0,
                    _as_text(row[positions[comment_id_col]]) if comment_id_col else "",
                    _as_text(row[positions[reply_user_col]]) if reply_user_col else "",
                    _as_text(row[positions[reply_id_col]]) if reply_id_col else "",
                ))
    return feeds, comments


def _read_contacts(conn: sqlite3.Connection, account_dir: str) -> tuple[list[tuple], str]:
    tables = _table_names(conn)
    table = "contact" if "contact" in tables else ("Contact" if "Contact" in tables else "")
    if not table:
        raise Weixin4Error("联系人数据库结构无法识别：" + ", ".join(tables[:12]))
    columns = _column_names(conn, table)
    user_col = _pick(columns, "username", "user_name", "UserName")
    nick_col = _pick(columns, "nick_name", "nickname", "NickName")
    remark_col = _pick(columns, "remark", "Remark")
    alias_col = _pick(columns, "alias", "Alias")
    small_col = _pick(columns, "small_head_url", "smallHeadImgUrl")
    big_col = _pick(columns, "big_head_url", "bigHeadImgUrl")
    py_col = _pick(columns, "pin_yin_initial", "PYInitial")
    remark_py_col = _pick(columns, "remark_pin_yin_initial", "RemarkPYInitial")
    if not user_col or not nick_col:
        raise Weixin4Error("联系人字段无法识别：" + ", ".join(columns[:12]))
    selected = [user_col, nick_col, remark_col, alias_col, small_col, big_col, py_col, remark_py_col]
    present = [name for name in selected if name]
    sql = "SELECT " + ", ".join(f'"{name}"' for name in present) + f' FROM "{table}"'
    index = {name: pos for pos, name in enumerate(present)}
    folder = os.path.basename(account_dir)
    people = []
    self_name = ""
    seen = set()
    for row in conn.execute(sql):
        username = _as_text(row[index[user_col]]).strip()
        nickname = _as_text(row[index[nick_col]]).strip()
        if not username or not nickname or username in seen:
            continue
        if username.startswith("gh_") or username.endswith("@chatroom") or username == "filehelper":
            continue
        seen.add(username)
        people.append((
            username,
            _as_text(row[index[alias_col]]) if alias_col else "",
            3,
            _as_text(row[index[remark_col]]) if remark_col else "",
            nickname,
            _as_text(row[index[py_col]]) if py_col else "",
            _as_text(row[index[remark_py_col]]) if remark_py_col else "",
            "",
            0,
            "",
            _as_text(row[index[small_col]]) if small_col else "",
            _as_text(row[index[big_col]]) if big_col else "",
        ))
        if (folder == username or folder.startswith(username + "_")) and len(username) > len(self_name):
            self_name = username
    return people, self_name


def _write_sns(path: str, feeds: list[tuple], comments: list[tuple]) -> None:
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE FeedsV20 (UserName TEXT, Content TEXT, FeedId INTEGER, CreateTime INTEGER)"
        )
        conn.execute(
            "CREATE TABLE CommentV20 (FromUserName TEXT, CommentType INTEGER, Content TEXT, "
            "FeedId INTEGER, CreateTime INTEGER, CommentId TEXT, ReplyUserName TEXT, ReplyId TEXT)"
        )
        conn.execute('CREATE TABLE SnsConfigV20 ("Key" TEXT, StrValue TEXT)')
        conn.executemany("INSERT INTO FeedsV20 VALUES (?,?,?,?)", feeds)
        if comments:
            normalized = []
            for item in comments:
                values = list(item[:8])
                values.extend([""] * (8 - len(values)))
                normalized.append(tuple(values))
            conn.executemany("INSERT INTO CommentV20 VALUES (?,?,?,?,?,?,?,?)", normalized)
        conn.commit()
    finally:
        conn.close()


def _write_contacts(path: str, people: list[tuple]) -> None:
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE Contact (UserName TEXT, Alias TEXT, Type INTEGER, Remark TEXT, NickName TEXT, "
            "PYInitial TEXT, RemarkPYInitial TEXT, ExTraBuf TEXT, VerifyFlag INTEGER, LabelIDList TEXT)"
        )
        conn.execute(
            "CREATE TABLE ContactHeadImgUrl (usrName TEXT, smallHeadImgUrl TEXT, bigHeadImgUrl TEXT)"
        )
        conn.execute("CREATE TABLE ContactLabel (LabelId TEXT, LabelName TEXT)")
        conn.executemany(
            "INSERT INTO Contact VALUES (?,?,?,?,?,?,?,?,?,?)",
            [person[:10] for person in people],
        )
        conn.executemany(
            "INSERT INTO ContactHeadImgUrl VALUES (?,?,?)",
            [(person[0], person[10], person[11]) for person in people],
        )
        conn.commit()
    finally:
        conn.close()


def _write_empty_msg(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE MSG (StrTalker TEXT, CreateTime INTEGER)")
        conn.commit()
    finally:
        conn.close()


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _pick(columns: list[str], *names: str) -> str:
    lookup = {column.lower(): column for column in columns}
    for name in names:
        if name.lower() in lookup:
            return lookup[name.lower()]
    return ""


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        if value.startswith(b"\x28\xb5\x2f\xfd"):
            try:
                import zstandard
                value = zstandard.ZstdDecompressor().decompress(value)
            except Exception:
                return ""
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return str(value)


def _as_int(value) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _timeline_xml(content: str) -> str:
    """把 4.x 的 SnsDataItem 收成现有导出器认识的 TimelineObject。"""
    if "TimelineObject" not in content:
        return content
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return content
    timeline = root if root.tag == "TimelineObject" else root.find("TimelineObject")
    if timeline is None:
        return content
    content_object = timeline.find("ContentObject")
    if content_object is not None and content_object.find("contentStyle") is None:
        style = content_object.findtext("type")
        if style:
            ElementTree.SubElement(content_object, "contentStyle").text = style
    return ElementTree.tostring(timeline, encoding="unicode")


def _create_time_from_xml(content: str) -> int:
    match = CREATE_TIME_RE.search(content)
    if match:
        return int(match.group(1))
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return 0
    text = root.attrib.get("createTime") or root.findtext("createTime") or ""
    return _as_int(text)
