import sqlite3
import unittest

from app.DataBase.sns import Sns
from entity.comment import Comment
from exporter.sns_interactions import render_interactions_html


class SnsInteractionTests(unittest.TestCase):
    def test_comment_rows_include_replies_and_sort_by_time(self):
        database = sqlite3.connect(":memory:")
        database.execute(
            """
            CREATE TABLE CommentV20 (
                FeedId TEXT,
                CommentId TEXT,
                CreateTime INTEGER,
                CommentType INTEGER,
                Content TEXT,
                FromUserName TEXT,
                ReplyUserName TEXT,
                ReplyId TEXT
            )
            """
        )
        database.executemany(
            """
            INSERT INTO CommentV20
            (FeedId, CommentId, CreateTime, CommentType, Content, FromUserName, ReplyUserName, ReplyId)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("feed-1", "c2", 200, 2, "第二条评论", "wxid_b", "wxid_a", "c1"),
                ("feed-1", "l1", 100, 1, "", "wxid_like", "", ""),
                ("feed-2", "x1", 150, 2, "其他动态", "wxid_x", "", ""),
            ],
        )

        handler = Sns()
        if handler.open_flag and handler.DB:
            handler.DB.close()
        handler.DB = database
        handler.cursor = database.cursor()
        handler.open_flag = True
        try:
            rows = handler.get_interactions_by_feed_id("feed-1")
            self.assertEqual([row["CommentId"] for row in rows], ["l1", "c2"])
            self.assertEqual(rows[1]["ReplyUserName"], "wxid_a")
        finally:
            handler.open_flag = False
            handler.DB = None
            handler.cursor = None
            database.close()

    def test_like_and_reply_comment_render_in_existing_markup(self):
        rows = [
            Comment("wxid_like", 1, ""),
            Comment("wxid_author", 2, "回复内容", reply_user_name="wxid_reply"),
        ]
        names = {
            "wxid_like": "点赞好友",
            "wxid_author": "评论好友",
            "wxid_reply": "被回复好友",
        }
        rendered = render_interactions_html(
            rows,
            lambda username: names.get(username, username),
            lambda value: value,
        )
        self.assertIn('class="moment-interactions pls"', rendered)
        self.assertIn("点赞好友", rendered)
        self.assertIn("评论好友", rendered)
        self.assertIn("回复", rendered)
        self.assertIn("被回复好友", rendered)
        self.assertIn("回复内容", rendered)

    def test_interaction_text_is_html_escaped(self):
        comment = Comment("wxid_author", 2, "<script>alert(1)</script>")
        rendered = render_interactions_html(
            [comment],
            lambda username: "作者",
            lambda value: value,
        )
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_empty_interactions_do_not_change_html(self):
        rendered = render_interactions_html([], lambda username: username, lambda value: value)
        self.assertEqual(rendered, "")


if __name__ == "__main__":
    unittest.main()
