import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Post, Comment, Prize, LotteryResult
from app.schemas import PrizeCreate, PrizeOut, LotteryResultOut, DrawRequest

router = APIRouter(prefix="/api/posts/{post_id}/lottery", tags=["lottery"])


def _get_post_or_404(post_id: int, db: Session) -> Post:
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="貼文不存在")
    return post


# ── Prizes ────────────────────────────────────────────────────────────────────

@router.get("/prizes", response_model=list[PrizeOut])
def list_prizes(post_id: int, db: Session = Depends(get_db)):
    _get_post_or_404(post_id, db)
    prizes = db.query(Prize).filter(Prize.post_id == post_id).all()
    result = []
    for p in prizes:
        drawn = db.query(LotteryResult).filter(LotteryResult.prize_id == p.id).count()
        out = PrizeOut.model_validate(p)
        out.drawn_count = drawn
        result.append(out)
    return result


@router.post("/prizes", response_model=PrizeOut, status_code=201)
def create_prize(post_id: int, body: PrizeCreate, db: Session = Depends(get_db)):
    _get_post_or_404(post_id, db)
    prize = Prize(post_id=post_id, name=body.name, quantity=body.quantity)
    db.add(prize)
    db.commit()
    db.refresh(prize)
    out = PrizeOut.model_validate(prize)
    out.drawn_count = 0
    return out


@router.delete("/prizes/{prize_id}", status_code=204)
def delete_prize(post_id: int, prize_id: int, db: Session = Depends(get_db)):
    _get_post_or_404(post_id, db)
    prize = db.query(Prize).filter(Prize.id == prize_id, Prize.post_id == post_id).first()
    if not prize:
        raise HTTPException(status_code=404, detail="獎品不存在")
    db.delete(prize)
    db.commit()


# ── Draw ──────────────────────────────────────────────────────────────────────

@router.post("/draw", response_model=LotteryResultOut)
def draw(post_id: int, body: DrawRequest, db: Session = Depends(get_db)):
    _get_post_or_404(post_id, db)

    prize = db.query(Prize).filter(Prize.id == body.prize_id, Prize.post_id == post_id).first()
    if not prize:
        raise HTTPException(status_code=404, detail="獎品不存在")

    drawn_count = db.query(LotteryResult).filter(LotteryResult.prize_id == prize.id).count()
    if drawn_count >= prize.quantity:
        raise HTTPException(status_code=400, detail=f"「{prize.name}」已抽完（共 {prize.quantity} 名）")

    already_won_usernames = {
        r.winner_username
        for r in db.query(LotteryResult).filter(LotteryResult.post_id == post_id).all()
    }

    comments = db.query(Comment).filter(Comment.post_id == post_id).all()
    seen = set()
    pool = []
    for c in comments:
        key = c.username or c.author
        if key and key not in seen and key not in already_won_usernames:
            seen.add(key)
            pool.append(c)

    if not pool:
        raise HTTPException(status_code=400, detail="沒有可抽的留言者（所有人都已得獎）")

    winner = random.choice(pool)
    result = LotteryResult(
        post_id=post_id,
        prize_id=prize.id,
        winner_username=winner.username or winner.author,
        winner_author=winner.author,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return LotteryResultOut(
        id=result.id,
        prize_id=prize.id,
        prize_name=prize.name,
        winner_username=result.winner_username,
        winner_author=result.winner_author,
        drawn_at=result.drawn_at,
    )


# ── Results ───────────────────────────────────────────────────────────────────

@router.get("/results", response_model=list[LotteryResultOut])
def list_results(post_id: int, db: Session = Depends(get_db)):
    _get_post_or_404(post_id, db)
    rows = (
        db.query(LotteryResult)
        .filter(LotteryResult.post_id == post_id)
        .order_by(LotteryResult.drawn_at.desc())
        .all()
    )
    out = []
    for r in rows:
        prize = db.query(Prize).filter(Prize.id == r.prize_id).first()
        out.append(LotteryResultOut(
            id=r.id,
            prize_id=r.prize_id,
            prize_name=prize.name if prize else "（已刪除）",
            winner_username=r.winner_username,
            winner_author=r.winner_author,
            drawn_at=r.drawn_at,
        ))
    return out


@router.delete("/results/{result_id}", status_code=204)
def delete_result(post_id: int, result_id: int, db: Session = Depends(get_db)):
    _get_post_or_404(post_id, db)
    result = db.query(LotteryResult).filter(
        LotteryResult.id == result_id,
        LotteryResult.post_id == post_id,
    ).first()
    if not result:
        raise HTTPException(status_code=404, detail="抽獎結果不存在")
    db.delete(result)
    db.commit()
