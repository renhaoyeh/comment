from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, nullable=False)
    post_code = Column(String, nullable=False)
    author = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    author = Column(String, nullable=True)
    username = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    likes = Column(Integer, default=0)
    created_at = Column(String, nullable=True)
    link = Column(String, nullable=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", back_populates="comments")


class Prize(Base):
    __tablename__ = "prizes"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post")
    results = relationship("LotteryResult", back_populates="prize", cascade="all, delete-orphan")


class LotteryResult(Base):
    __tablename__ = "lottery_results"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    prize_id = Column(Integer, ForeignKey("prizes.id"), nullable=False)
    winner_username = Column(String, nullable=False)
    winner_author = Column(String, nullable=True)
    drawn_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post")
    prize = relationship("Prize", back_populates="results")
