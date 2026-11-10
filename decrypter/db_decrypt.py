import os
import shutil
import sqlite3
import tkinter
import traceback

from pywxdump import decrypt
from helper.db_snapshot import copy_sqlite_snapshot
from log import LOG


class DatabaseDecrypter:

    def __init__(self, gui: 'Gui', db_path, key):
        self.db_path = db_path
        self.key = key
        self.gui = gui
        account_info = getattr(gui, "account_info", None) or {}
        self.output_dir = account_info.get("databaseDir") or os.path.join(
            account_info.get("profileCacheDir") or "account_cache", "database"
        )
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
        if self.gui.account_info and self.gui.account_info.get("weixin4"):
            return self._decrypt_weixin4()

        output_dir = self.output_dir
        os.makedirs(output_dir, exist_ok=True)
        tasks = []
        source_snapshot_dir = os.path.join(
            (getattr(self.gui, "account_info", None) or {}).get("profileCacheDir")
            or os.path.dirname(output_dir),
            "encrypted_source",
        )
        os.makedirs(source_snapshot_dir, exist_ok=True)

        # 每次重建当前 wxid 的数据库缓存前先清除旧解密库，避免残留分片混入新快照。
        for existing_name in os.listdir(output_dir):
            if existing_name in self.db_list or (
                existing_name.startswith("MSG") and existing_name.endswith(".db")
            ):
                existing_path = os.path.join(output_dir, existing_name)
                if os.path.isfile(existing_path):
                    os.remove(existing_path)
        if os.path.exists(self.db_path):
            for root, dirs, files in os.walk(self.db_path):
                for file in files:
                    if file.endswith(".db") and file in self.db_list:
                        in_path = os.path.join(root, file)
                        relative = os.path.relpath(in_path, self.db_path)
                        snapshot_path = os.path.join(source_snapshot_dir, relative)
                        os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
                        try:
                            copy_sqlite_snapshot(in_path, snapshot_path, retries=3)
                        except Exception as exc:
                            LOG.error(f"复制账号数据库快照失败：{in_path}: {exc}")
                            continue
                        output_path = os.path.join(output_dir, file)
                        if os.path.exists(output_path):
                            os.remove(output_path)
                        tasks.append([self.key, snapshot_path, output_path])
        if not tasks:
            raise RuntimeError("所选微信账号目录中没有可读取的数据库")
        for i, task in enumerate(tasks):
            flag, result = decrypt(*task)
            if not flag:
                LOG.error(result)
            progress = round((i+1) / len(tasks) * 100)
            self.gui.update_decrypt_progressbar(progress)

        for required_name in ("MicroMsg.db", "Sns.db", "MSG0.db"):
            required_path = os.path.join(output_dir, required_name)
            if not os.path.isfile(required_path) or os.path.getsize(required_path) == 0:
                raise RuntimeError(
                    f"{required_name} 解密失败或文件缺失，请核对所选账号目录和手动输入的数据库密钥"
                )

        target_database = os.path.join(output_dir, "MSG.db")
        # 源数据库文件列表
        # MSG0 已被复制为目标库模板，不应再次插入，否则该分片会重复。
        source_databases = [os.path.join(output_dir, f"MSG{i}.db") for i in range(1, 50)]
        if os.path.exists(target_database):
            os.remove(target_database)
        try:
            shutil.copy2(os.path.join(output_dir, "MSG0.db"), target_database)  # 使用一个数据库文件作为模板
        except FileNotFoundError:
            LOG.error(traceback.format_exc())
        # 合并数据库
        try:
            self.merge_databases(source_databases, target_database)
        except FileNotFoundError:
            LOG.error(traceback.format_exc())
            LOG.error("数据库不存在\n请检查微信版本是否为最新")

        # 解密完成 放开下一步按钮
        if self.gui.account_info is not None:
            self.gui.account_info["databaseDir"] = output_dir
        self.gui.decrypt_note_text.set("所选账号的数据已复制，请点击下一步")
        self.gui.next_step_button.config(state=tkinter.NORMAL)
        return True

    def _decrypt_weixin4(self) -> bool:
        from decrypter.weixin4 import Weixin4Error, build_export_databases_with_manual_keys

        def progress(value, text):
            self.gui.update_decrypt_progressbar(value)
            if text:
                self.gui.decrypt_note_text.set(text)

        try:
            account_info = self.gui.account_info or {}
            manual_keys = account_info.get("manual_keys") or {}
            if not manual_keys.get("sns_db_key") or not manual_keys.get("contact_db_key"):
                raise Weixin4Error("该微信 4.x 账号尚未配置数据库密钥，请在账号档案中手动填写")
            build_export_databases_with_manual_keys(
                account_info,
                manual_keys,
                account_info.get("profileCacheDir") or self.output_dir,
                progress,
            )
            self.output_dir = account_info.get("databaseDir") or self.output_dir
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


