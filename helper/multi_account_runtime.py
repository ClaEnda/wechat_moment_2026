from __future__ import annotations

import os

from helper.account_profiles import AccountProfileError


def activate_account_database(database_dir: str) -> None:
    """
    将所选 wxid 的独立数据库目录挂接到旧版导出器的数据库访问层。
    连接先关闭，再更新路径，避免账号 A 的 SQLite 连接残留到账号 B。
    """
    database_dir = os.path.abspath(database_dir)
    if not os.path.isdir(database_dir):
        raise AccountProfileError(f"账号数据库缓存不存在：{database_dir}")

    from app.DataBase import micro_msg_db, misc_db, msg_db, sns_db
    from app.DataBase import micro_msg, misc, msg, sns

    mappings = [
        (micro_msg_db, micro_msg, "MicroMsg.db"),
        (misc_db, misc, "Misc.db"),
        (msg_db, msg, "MSG.db"),
        (sns_db, sns, "Sns.db"),
    ]

    for instance, _module, _filename in mappings:
        if getattr(instance, "open_flag", False):
            instance.close()

    for instance, module, filename in mappings:
        module.db_path = os.path.join(database_dir, filename)
        if os.path.isfile(module.db_path):
            instance.init_database()

    if not os.path.isfile(os.path.join(database_dir, "Sns.db")):
        raise AccountProfileError("所选账号的朋友圈数据库不存在")
    if not os.path.isfile(os.path.join(database_dir, "MicroMsg.db")):
        raise AccountProfileError("所选账号的联系人数据库不存在")
