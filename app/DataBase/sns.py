import os.path
import random
import sqlite3
import threading
import traceback
from typing import Optional

db_path = "./app/Database/Msg/Sns.db"
lock = threading.Lock()


def is_database_exist():
    return os.path.exists(db_path)


def singleton(cls):
    _instance = {}

    def inner():
        if cls not in _instance:
            _instance[cls] = cls()
        return _instance[cls]

    return inner

@singleton
class Sns:
    def __init__(self):
        self.DB = None
        self.cursor = None
        self.open_flag = False
        self.init_database()

    def init_database(self, path=None):
        global db_path
        if not self.open_flag:
            if path:
                db_path = path
            if os.path.exists(db_path):
                self.DB = sqlite3.connect(db_path, check_same_thread=False)
                # '''创建游标'''
                self.cursor = self.DB.cursor()
                self.open_flag = True
                if lock.locked():
                    lock.release()

    def get_messages_in_time(self, start_time, end_time):
        if not self.open_flag:
            return None
        try:
            lock.acquire(True)
            sql = '''select UserName, Content, FeedId from FeedsV20  where CreateTime>=?
                  and  CreateTime<=? order by CreateTime desc'''
            self.cursor.execute(sql, [start_time, end_time])
            res = self.cursor.fetchall()
        finally:
            lock.release()

        return res

    def get_comment_by_feed_id(self, feed_id):
        if not self.open_flag:
            return None
        try:
            lock.acquire(True)
            sql = '''select FromUserName, CommentType, Content from CommentV20 where FeedId=?
                   order by CreateTime desc'''
            self.cursor.execute(sql, [feed_id])
            res = self.cursor.fetchall()
        finally:
            lock.release()
        return res

    def get_interactions_by_feed_id(self, feed_id):
        """
        读取一条朋友圈的点赞与评论记录。

        微信客户端不同版本的 CommentV20 字段可能略有差异，因此先读取表结构，
        再只选择实际存在的字段。Content 为空的记录作为点赞，存在正文的记录作为评论。
        """
        if not self.open_flag:
            return []

        acquired = False
        try:
            lock.acquire(True)
            acquired = True
            self.cursor.execute("PRAGMA table_info('CommentV20')")
            schema = self.cursor.fetchall()
            columns = {str(row[1]).lower(): str(row[1]) for row in schema}

            required = ("feedid", "fromusername", "content")
            if any(name not in columns for name in required):
                return []

            field_names = (
                "FeedId",
                "CommentId",
                "CreateTime",
                "CommentType",
                "Content",
                "FromUserName",
                "ReplyUserName",
                "ReplyId",
            )
            selected = [columns[name.lower()] for name in field_names if name.lower() in columns]
            select_sql = ", ".join('"' + name.replace('"', '""') + '"' for name in selected)
            feed_column = '"' + columns["feedid"].replace('"', '""') + '"'
            order_column = columns.get("createtime")
            if order_column:
                order_sql = ' ORDER BY "' + order_column.replace('"', '""') + '" ASC'
            else:
                order_sql = " ORDER BY rowid ASC"

            sql = f"SELECT {select_sql} FROM CommentV20 WHERE {feed_column}=?{order_sql}"
            try:
                self.cursor.execute(sql, [feed_id])
            except sqlite3.OperationalError:
                # 少数非标准表结构没有 rowid，退回不排序读取。
                sql = f"SELECT {select_sql} FROM CommentV20 WHERE {feed_column}=?"
                self.cursor.execute(sql, [feed_id])

            rows = self.cursor.fetchall()
            records = [dict(zip(selected, row)) for row in rows]

            # 某些微信版本只写入 ReplyId；此时用同一动态中的 CommentId 反查回复对象。
            author_by_comment_id = {
                str(record.get("CommentId")): str(record.get("FromUserName") or "")
                for record in records
                if record.get("CommentId") is not None
            }
            for record in records:
                if not record.get("ReplyUserName") and record.get("ReplyId") is not None:
                    record["ReplyUserName"] = author_by_comment_id.get(
                        str(record.get("ReplyId")), ""
                    )

            return records
        except sqlite3.Error:
            # 数据库版本不兼容或没有互动表时，保留朋友圈正文导出，不中断整个任务。
            return []
        finally:
            if acquired:
                lock.release()

    def get_cover_url(self) -> Optional[str]:
        if not self.open_flag:
            return None
        try:
            lock.acquire(True)
            sql = '''select StrValue from SnsConfigV20 where Key="6"  '''
            self.cursor.execute(sql)
            result = self.cursor.fetchall()
            if result:
                return result[0][0]
        finally:
            lock.release()
        return None

    def get_earliest_timestamp(self):
        """返回本地已缓存动态里最早的一条发布时间。没有记录时返回 None。"""
        if not self.open_flag:
            return None
        sql = """
            select min(CreateTime)
            from FeedsV20
            where CreateTime > 0
        """
        try:
            lock.acquire(True)
            self.cursor.execute(sql)
            row = self.cursor.fetchone()
            if row and row[0]:
                return int(row[0])
        finally:
            lock.release()
        return None

    def close(self):
        if self.open_flag:
            try:
                lock.acquire(True)
                self.open_flag = False
                self.DB.close()
            finally:
                lock.release()

    def __del__(self):
        self.close()


if __name__ == '__main__':
    pass
