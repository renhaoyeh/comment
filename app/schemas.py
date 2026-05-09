from datetime import datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl


class ScrapeRequest(BaseModel):
    url: str


class CommentOut(BaseModel):
    id: int
    author: Optional[str]
    username: Optional[str]
    content: Optional[str]
    likes: int
    created_at: Optional[str]
    link: Optional[str]
    scraped_at: datetime

    model_config = {"from_attributes": True}


class PostOut(BaseModel):
    id: int
    url: str
    post_code: str
    author: Optional[str]
    content: Optional[str]
    scraped_at: datetime
    comments: list[CommentOut] = []

    model_config = {"from_attributes": True}


class PostSummary(BaseModel):
    id: int
    url: str
    post_code: str
    author: Optional[str]
    scraped_at: datetime
    comment_count: int

    model_config = {"from_attributes": True}


class ScrapeResponse(BaseModel):
    post_id: int
    comments_count: int
    comments: list[CommentOut]
