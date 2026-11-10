from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path


class DatabaseSnapshotError(RuntimeError):
    pass


def _signature(path: str):
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _copy_atomic(source: str, destination: str) -> None:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="db-snapshot-", dir=os.path.dirname(destination))
    os.close(fd)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def copy_sqlite_snapshot(source_db: str, destination_db: str, retries: int = 3) -> None:
    """
    复制 SQLite 主库及 WAL/SHM 边车文件，并检查复制窗口内源文件是否变化。
    检测到微信仍在写入时短暂重试；不能得到稳定快照时明确失败，不解密不完整副本。
    """
    source_db = os.path.abspath(source_db)
    destination_db = os.path.abspath(destination_db)
    if not os.path.isfile(source_db):
        raise DatabaseSnapshotError(f"数据库文件不存在：{source_db}")

    pairs = [
        (source_db, destination_db),
        (source_db + "-wal", destination_db + "-wal"),
        (source_db + "-shm", destination_db + "-shm"),
    ]

    last_error = None
    for attempt in range(max(1, retries)):
        before = {src: _signature(src) for src, _dst in pairs}
        if before[source_db] is None:
            raise DatabaseSnapshotError(f"数据库文件已消失：{source_db}")
        try:
            for src, dst in pairs:
                if before[src] is None:
                    if os.path.exists(dst):
                        os.remove(dst)
                    continue
                _copy_atomic(src, dst)
            after = {src: _signature(src) for src, _dst in pairs}
            if before == after:
                return
            last_error = "微信正在更新数据库文件"
        except OSError as exc:
            last_error = str(exc)
        if attempt + 1 < max(1, retries):
            time.sleep(0.2 * (attempt + 1))

    raise DatabaseSnapshotError(
        f"无法取得稳定的账号数据库快照，请稍后重试：{last_error or source_db}"
    )
