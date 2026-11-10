import os
import sqlite3
import tkinter
import traceback

from pywxdump import decrypt
from log import LOG


class DatabaseDecrypter:

    def __init__(self, gui: 'Gui', db_path, key):
        self.db_path = db_path
        self.key = key
        self.gui = gui
        # 指定需要解密的数据库
        self.db_list = ["MicroMsg.db", "Misc.db", "MSG.db", "Sns.db"]
        self.db_list.extend([f"MSG{i}.db" for i in range(0, 50)])

    def merge_databases(self, source_paths, target_path):
        # 创建目标数据库连接
        target_conn = sqlite3.connect(target_path)
        target_cursor = target_conn.cursor()
        try:
            # 开始事务
            target_conn.execute("BEGIN;")
            for i, source_path in enumerate(source_paths):
                if not os.path.exists(source_path):
                    continue
                db = sqlite3.connect(source_path)
                db.text_factory = str
                cursor = db.cursor()
                try:
                    sql = '''
                        SELECT TalkerId,MsgsvrID,Type,SubType,IsSender,CreateTime,Sequence,StrTalker,StrContent,DisplayContent,BytesExtra,CompressContent
                        FROM MSG;
                    '''
                    cursor.execute(sql)
                    result = cursor.fetchall()
                    # 附加源数据库
                    target_cursor.executemany(
                        "INSERT INTO MSG "
                        "(TalkerId,MsgsvrID,Type,SubType,IsSender,CreateTime,Sequence,StrTalker,StrContent,DisplayContent,"
                        "BytesExtra,CompressContent)"
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        result)
                except:
                    LOG.error(f'{source_path}数据库合并错误:\n{traceback.format_exc()}')
                cursor.close()
                db.close()
            # 提交事务
            target_conn.execute("COMMIT;")

        except Exception as e:
            # 发生异常时回滚事务
            target_conn.execute("ROLLBACK;")
            raise e

        finally:
            # 关闭目标数据库连接
            target_conn.close()

    def decrypt(self) -> bool:
        account_info = self.gui.account_info or {}
        from account_profiles import AccountProfileStore

        store = AccountProfileStore()
        profile = {
            "profile_id": account_info.get("profile_id"),
            "account_dir": account_info.get("filePath") or account_info.get("account_dir") or "",
        }
        if not profile["profile_id"]:
            profile["profile_id"] = store.profile_id_for_path(profile["account_dir"])
        profile_id = profile["profile_id"]
        workspace = store.workspace_for(profile)
        output_dir = account_info.get("databaseCopyPath") or str(workspace / "database")
        os.makedirs(output_dir, exist_ok=True)
        account_info["workspaceDir"] = str(workspace)
        account_info["databaseCopyPath"] = output_dir

        if account_info.get("weixin4"):
            return self._decrypt_weixin4()

        tasks = []
        key = self.key
        if not key:
            secrets = store.load_secrets(profile_id)
            key = secrets.get("legacy_db_key", "")
            secrets.clear()
        if not key:
            self.gui.decrypt_note_text.set("请在账号设置中输入该账号数据库密钥")
            self.gui.next_step_button.config(state=tkinter.NORMAL)
            return False

        if os.path.exists(self.db_path):
            for root, dirs, files in os.walk(self.db_path):
                for file in files:
                    if file.endswith(".db") and file in self.db_list:
                        in_path = os.path.join(root, file)
                        output_path = os.path.join(output_dir, file)
                        tasks.append([key, in_path, output_path])
        if not tasks:
            self.gui.decrypt_note_text.set("所选账号目录中没有可解密的数据库")
            self.gui.next_step_button.config(state=tkinter.NORMAL)
            return False

        for i, task in enumerate(tasks):
            try:
                flag, result = decrypt(*task)
            except Exception:
                LOG.error(traceback.format_exc())
                self.gui.decrypt_note_text.set(f"解密数据库失败：{os.path.basename(task[1])}")
                self.gui.next_step_button.config(state=tkinter.NORMAL)
                return False
            if not flag:
                LOG.error(str(result))
                self.gui.decrypt_note_text.set(f"解密数据库失败：{os.path.basename(task[1])}")
                self.gui.next_step_button.config(state=tkinter.NORMAL)
                return False
            progress = round((i + 1) / len(tasks) * 100)
            self.gui.update_decrypt_progressbar(progress)

        target_database = os.path.join(output_dir, "MSG.db")
        source_databases = [os.path.join(output_dir, f"MSG{i}.db") for i in range(0, 50)]
        if os.path.exists(target_database):
            os.remove(target_database)
        try:
            import shutil
            shutil.copy2(os.path.join(output_dir, "MSG0.db"), target_database)
            self.merge_databases(source_databases, target_database)
        except FileNotFoundError as exc:
            LOG.error(traceback.format_exc())
            self.gui.decrypt_note_text.set("所选账号缺少聊天数据库，请检查账号目录和密钥")
            self.gui.next_step_button.config(state=tkinter.NORMAL)
            return False

        from app.DataBase import use_database_dir
        use_database_dir(output_dir)
        self.gui.decrypt_note_text.set("所选账号数据库复制成功，请点击下一步")
        self.gui.next_step_button.config(state=tkinter.NORMAL)
        return True

    def _decrypt_weixin4(self) -> bool:
        from decrypter.weixin4 import Weixin4Error, build_export_databases

        def progress(value, text):
            self.gui.update_decrypt_progressbar(value)
            if text:
                self.gui.decrypt_note_text.set(text)

        try:
            build_export_databases(self.gui.account_info, progress)
            from app.DataBase import use_database_dir
            use_database_dir(self.gui.account_info["databaseCopyPath"])
        except Weixin4Error as exc:
            LOG.error(str(exc))
            self.gui.decrypt_note_text.set(str(exc))
            self.gui.next_step_button.config(state=tkinter.NORMAL)
            return False
        except Exception:
            LOG.error(traceback.format_exc())
            self.gui.decrypt_note_text.set("读取微信 4.1 数据失败")
            self.gui.next_step_button.config(state=tkinter.NORMAL)
            return False
        self.gui.next_step_button.config(state=tkinter.NORMAL)
        return True


