from html import escape
from typing import Callable, Iterable

from entity.comment import Comment


def render_interactions_html(
    interactions: Iterable[Comment],
    resolve_name: Callable[[str], str],
    replace_emoji: Callable[[str], str],
) -> str:
    """把本地朋友圈互动记录渲染进原有时间线样式，不引入新的页面框架。"""
    likes: list[str] = []
    like_seen: set[str] = set()
    comments: list[Comment] = []

    for interaction in interactions:
        username = interaction.from_user_name
        display_name = resolve_name(username) if username else "未知用户"
        display_name = display_name or username or "未知用户"

        if interaction.is_like:
            if display_name not in like_seen:
                like_seen.add(display_name)
                likes.append(display_name)
        else:
            comments.append(interaction)

    if not likes and not comments:
        return ""

    parts = ['<div class="moment-interactions pls">']

    if likes:
        rendered_names = "、".join(
            f'<span class="like-name">{escape(name, quote=True)}</span>'
            for name in likes
        )
        parts.append(
            '<div class="moment-like-line">'
            '<span class="interaction-label">赞</span> '
            f'{rendered_names}'
            '</div>'
        )

    for interaction in comments:
        author_id = interaction.from_user_name
        author = resolve_name(author_id) if author_id else "未知用户"
        author = author or author_id or "未知用户"

        line = (
            '<div class="moment-comment-line">'
            f'<span class="comment-author">{escape(author, quote=True)}</span>'
        )

        reply_id = interaction.reply_user_name.strip()
        if reply_id:
            reply_name = resolve_name(reply_id) or reply_id
            line += (
                ' 回复 '
                f'<span class="reply-author">{escape(reply_name, quote=True)}</span>'
            )

        content = escape(interaction.content, quote=True)
        content = replace_emoji(content)
        content = content.replace("\r\n", "<br>").replace("\r", "<br>").replace("\n", "<br>")
        line += f'：{content}</div>'
        parts.append(line)

    parts.append("</div>")
    return "\n".join(parts) + "\n"
