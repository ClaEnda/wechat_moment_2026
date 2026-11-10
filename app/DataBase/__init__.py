# -*- coding: utf-8 -*-
"""
@File    : __init__.py.py
@Author  : Shuaikang Zhou
@Time    : 2023/1/5 0:10
@IDE     : Pycharm
@Version : Python3.10
@comment : ···
"""
from .micro_msg import MicroMsg
from .misc import Misc
from .msg import Msg
from .sns import Sns

misc_db = Misc()
msg_db = Msg()
micro_msg_db = MicroMsg()
sns_db = Sns()


__all__ = ['misc_db', 'micro_msg_db', 'msg_db', "sns_db"]


def use_database_dir(directory):
    """切换到一个账号专属的已解密数据库目录。一次只激活一个账号供当前导出任务使用。"""
    import os
    from . import misc as misc_module
    from . import micro_msg as micro_msg_module
    from . import msg as msg_module
    from . import sns as sns_module

    os.makedirs(directory, exist_ok=True)
    databases = (misc_db, micro_msg_db, msg_db, sns_db)
    for database in databases:
        try:
            database.close()
        except Exception:
            pass

    misc_module.db_path = os.path.join(directory, "Misc.db")
    micro_msg_module.db_path = os.path.join(directory, "MicroMsg.db")
    msg_module.db_path = os.path.join(directory, "MSG.db")
    sns_module.db_path = os.path.join(directory, "Sns.db")

    for database in databases:
        database.init_database()
