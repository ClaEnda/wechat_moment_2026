from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Comment:
    """一条朋友圈互动记录；空正文表示点赞，非空正文表示评论。"""

    from_user_name: str
    comment_type: Optional[int]
    content: str
    comment_id: str = ""
    create_time: int = 0
    reply_user_name: str = ""
    reply_id: str = ""

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "Comment":
        raw_type = row.get("CommentType")
        try:
            comment_type = int(raw_type) if raw_type is not None else None
        except (TypeError, ValueError):
            comment_type = None

        raw_time = row.get("CreateTime")
        try:
            create_time = int(raw_time) if raw_time is not None else 0
        except (TypeError, ValueError):
            create_time = 0

        return cls(
            from_user_name=str(row.get("FromUserName") or ""),
            comment_type=comment_type,
            content=str(row.get("Content") or ""),
            comment_id=str(row.get("CommentId") or ""),
            create_time=create_time,
            reply_user_name=str(row.get("ReplyUserName") or ""),
            reply_id=str(row.get("ReplyId") or ""),
        )

    @property
    def is_like(self) -> bool:
        # CommentV20 同表保存点赞与评论；点赞记录通常没有 Content 正文。
        return not self.content.strip()
