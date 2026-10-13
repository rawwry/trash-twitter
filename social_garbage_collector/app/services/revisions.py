"""Nachvollziehbare manuelle Aenderungen und Loeschvermerke."""

import json

from sqlalchemy.orm import Session

from ..models import Post, PostRevision, User


def record(db: Session, post: Post, user: User | None, action: str) -> None:
    fields = ("url", "author_handle", "author_display_name", "text", "text_source",
              "posted_at", "date_source", "date_has_time", "note", "screenshot_path",
              "shot_source", "thread_extra", "snapshot_at")
    snapshot = {name: getattr(post, name) for name in fields}
    snapshot["tags"] = [tag.name for tag in post.tags]
    snapshot["lists"] = [link.list_id for link in post.list_links]
    db.add(PostRevision(post_id=post.id, actor_name=user.username if user else "System",
                        action=action, snapshot=json.dumps(snapshot, default=str, ensure_ascii=False)))
