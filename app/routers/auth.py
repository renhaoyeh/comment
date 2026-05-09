import json
import asyncio
import concurrent.futures
from pathlib import Path
from fastapi import APIRouter, HTTPException

SESSION_PATH = Path("data/session.json")
THREADS_URL = "https://www.threads.net"

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_future: concurrent.futures.Future | None = None
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def session_exists() -> bool:
    return SESSION_PATH.exists() and SESSION_PATH.stat().st_size > 0


@router.get("/status")
def auth_status():
    return {"logged_in": session_exists()}


@router.post("/logout")
def logout():
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()
    return {"logged_in": False}


@router.post("/login")
async def login():
    global _login_future

    if _login_future and not _login_future.done():
        raise HTTPException(status_code=409, detail="登入視窗已開啟，請完成登入後再試")

    loop = asyncio.get_running_loop()
    _login_future = loop.run_in_executor(_executor, _run_login_in_thread)
    return {"message": "登入視窗已開啟，請在彈出的瀏覽器中完成登入，完成後點擊視窗內的「儲存登入狀態」按鈕"}


def _run_login_in_thread():
    """Run Playwright login in a dedicated thread with its own event loop (Windows-safe)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_do_login())
    finally:
        loop.close()


async def _do_login():
    from playwright.async_api import async_playwright

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            no_viewport=True,
        )

        if session_exists():
            try:
                data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if data.get("cookies"):
                    await context.add_cookies(data["cookies"])
            except Exception:
                pass

        page = await context.new_page()
        await page.goto(f"{THREADS_URL}/login", wait_until="domcontentloaded")

        await page.evaluate("""() => {
            const btn = document.createElement('button');
            btn.id = '__save_session_btn__';
            btn.innerText = '✅ 儲存登入狀態';
            btn.style.cssText = `
                position: fixed; bottom: 24px; right: 24px; z-index: 999999;
                background: #0095f6; color: white; font-size: 15px; font-weight: bold;
                padding: 12px 24px; border: none; border-radius: 24px;
                cursor: pointer; box-shadow: 0 4px 16px rgba(0,0,0,0.3);
            `;
            btn.onclick = () => { window.__SESSION_SAVE__ = true; btn.innerText = '儲存中...'; btn.disabled = true; };
            document.body.appendChild(btn);
        }""")

        # Poll until user clicks save button (max 5 min)
        for _ in range(300):
            await asyncio.sleep(1)
            try:
                if await page.evaluate("() => !!window.__SESSION_SAVE__"):
                    break
            except Exception:
                break

        cookies = await context.cookies()
        storage = {}
        try:
            storage = await page.evaluate("() => ({ ...localStorage })")
        except Exception:
            pass

        SESSION_PATH.write_text(
            json.dumps({"cookies": cookies, "localStorage": storage}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        try:
            await page.evaluate("""() => {
                const btn = document.getElementById('__save_session_btn__');
                if (btn) { btn.innerText = '✅ 已儲存！視窗將自動關閉'; }
            }""")
        except Exception:
            pass

        await asyncio.sleep(2)
        await browser.close()
