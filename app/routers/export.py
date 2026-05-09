import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd

from app.database import get_db
from app.models import Post, Comment

router = APIRouter(prefix="/api/export", tags=["export"])


def _build_df(post: Post) -> pd.DataFrame:
    rows = [
        {
            "作者名稱": c.author,
            "帳號": c.username,
            "留言內容": c.content,
            "留言連結": c.link or "",
            "按讚數": c.likes,
            "發文時間": c.created_at,
            "撈取時間": c.scraped_at.strftime("%Y-%m-%d %H:%M:%S") if c.scraped_at else "",
        }
        for c in post.comments
    ]
    return pd.DataFrame(rows)


@router.get("/csv")
def export_csv(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="貼文不存在")

    df = _build_df(post)
    buf = io.StringIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)

    filename = f"threads_{post.post_code}_comments.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/excel")
def export_excel(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="貼文不存在")

    df = _build_df(post)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="留言")
    buf.seek(0)

    filename = f"threads_{post.post_code}_comments.xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
