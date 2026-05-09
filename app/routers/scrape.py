import json
import asyncio
import concurrent.futures
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Post, Comment
from app.schemas import ScrapeRequest, ScrapeResponse, CommentOut, PostSummary
from app.scraper import scrape_threads_post, ScrapedPost

router = APIRouter(prefix="/api", tags=["scrape"])


def _save_to_db(url: str, scraped: ScrapedPost) -> int:
    """Persist scraped post and comments; returns post.id."""
    db = SessionLocal()
    try:
        post = db.query(Post).filter(Post.url == url).first()
        if post:
            db.query(Comment).filter(Comment.post_id == post.id).delete()
            post.author = scraped.author
            post.content = scraped.content
            post.scraped_at = datetime.utcnow()
        else:
            post = Post(
                url=url,
                post_code=scraped.post_code,
                author=scraped.author,
                content=scraped.content,
            )
            db.add(post)
            db.flush()

        for sc in scraped.comments:
            db.add(Comment(
                post_id=post.id,
                author=sc.author,
                username=sc.username,
                content=sc.content,
                likes=sc.likes,
                created_at=sc.created_at,
                link=sc.link,
            ))

        db.commit()
        return post.id
    finally:
        db.close()


@router.get("/scrape/stream")
async def scrape_stream(url: str = Query(...)):
    """SSE endpoint: streams scraping progress then saves to DB."""
    url = url.strip().rstrip("/")

    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_progress(event: str, payload: dict):
        msg = json.dumps({"event": event, **payload}, ensure_ascii=False)
        loop.call_soon_threadsafe(queue.put_nowait, f"data: {msg}\n\n")

    async def run_scraper():
        try:
            scraped = await scrape_threads_post(url, on_progress=on_progress)
            post_id = await loop.run_in_executor(None, _save_to_db, url, scraped)
            done_msg = json.dumps({"event": "saved", "post_id": post_id, "count": len(scraped.comments)}, ensure_ascii=False)
            await queue.put(f"data: {done_msg}\n\n")
        except Exception as e:
            err_msg = json.dumps({"event": "error", "msg": str(e)}, ensure_ascii=False)
            await queue.put(f"data: {err_msg}\n\n")
        finally:
            await queue.put(None)  # sentinel

    asyncio.create_task(run_scraper())

    async def event_generator():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest, db: Session = Depends(get_db)):
    """Non-streaming fallback."""
    url = req.url.strip().rstrip("/")
    try:
        scraped = await scrape_threads_post(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"爬蟲失敗：{e}")

    post_id = await asyncio.get_running_loop().run_in_executor(None, _save_to_db, url, scraped)

    post = db.query(Post).filter(Post.id == post_id).first()
    comments_out = [CommentOut.model_validate(c) for c in post.comments]
    return ScrapeResponse(post_id=post_id, comments_count=len(comments_out), comments=comments_out)


@router.get("/posts", response_model=list[PostSummary])
def list_posts(db: Session = Depends(get_db)):
    posts = db.query(Post).order_by(Post.scraped_at.desc()).all()
    return [
        PostSummary(
            id=p.id,
            url=p.url,
            post_code=p.post_code,
            author=p.author,
            scraped_at=p.scraped_at,
            comment_count=len(p.comments),
        )
        for p in posts
    ]


@router.get("/posts/{post_id}/comments", response_model=list[CommentOut])
def get_comments(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="貼文不存在")
    return [CommentOut.model_validate(c) for c in post.comments]


@router.delete("/posts/{post_id}")
def delete_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="貼文不存在")
    db.delete(post)
    db.commit()
    return {"ok": True}
