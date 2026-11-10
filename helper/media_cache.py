from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date
from pathlib import Path


def _months_between(start_date: date, end_date: date) -> list[str]:
    months = []
    current = date(start_date.year, start_date.month, 1)
    end = date(end_date.year, end_date.month, 1)
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        year = current.year + (current.month // 12)
        month = current.month % 12 + 1
        current = date(year, month, 1)
    return months


def snapshot_sns_media_cache(
    account_dir: str,
    media_cache_dir: str,
    start_date: date,
    end_date: date,
) -> int:
    """
    将所选账号时间范围内的本地朋友圈媒体缓存复制到 wxid 独立目录。
    原微信目录保持只读；复制失败的单个文件会跳过并由后续导出过程记录。
    """
    source_root = Path(account_dir) / "FileStorage" / "Sns" / "Cache"
    target_root = Path(media_cache_dir)
    if not source_root.is_dir():
        target_root.mkdir(parents=True, exist_ok=True)
        return 0

    copied = 0
    for month in _months_between(start_date, end_date):
        source_month = source_root / month
        if not source_month.is_dir():
            continue
        for source in source_month.rglob("*"):
            if not source.is_file():
                continue
            try:
                relative = source.relative_to(source_root)
                destination = target_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                source_stat = source.stat()
                if destination.is_file():
                    target_stat = destination.stat()
                    if target_stat.st_size == source_stat.st_size and target_stat.st_mtime >= source_stat.st_mtime:
                        continue

                fd, temp_path = tempfile.mkstemp(prefix="sns-cache-", dir=str(destination.parent))
                os.close(fd)
                try:
                    shutil.copy2(source, temp_path)
                    os.replace(temp_path, destination)
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                copied += 1
            except OSError:
                continue
    return copied
