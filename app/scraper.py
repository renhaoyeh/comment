import re
import json
import asyncio
import concurrent.futures
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field

SESSION_PATH = Path("data/session.json")

MAX_SCROLL_ROUNDS = 60
SCROLL_WAIT = 4.0

# Type alias for progress callback: (event, payload) -> None
ProgressCb = Callable[[str, dict], None]


@dataclass
class ScrapedComment:
    author: str = ""
    username: str = ""
    content: str = ""
    likes: int = 0
    created_at: str = ""
    link: str = ""


@dataclass
class ScrapedPost:
    url: str = ""
    post_code: str = ""
    author: str = ""
    content: str = ""
    comments: list[ScrapedComment] = field(default_factory=list)


def _extract_post_code(url: str) -> Optional[str]:
    match = re.search(r"/post/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def _parse_comment_node(node: dict) -> Optional[ScrapedComment]:
    try:
        user = node.get("user", {})
        caption = node.get("caption") or {}
        username = user.get("username", "")
        code = node.get("code", "")
        link = f"https://www.threads.net/@{username}/post/{code}" if username and code else ""
        return ScrapedComment(
            author=user.get("full_name", ""),
            username=username,
            content=caption.get("text", "") if isinstance(caption, dict) else str(caption),
            likes=node.get("like_count", 0),
            created_at=str(node.get("taken_at", "")),
            link=link,
        )
    except Exception:
        return None


def _parse_threads_json(data: dict, original_post_code: str = "") -> tuple[dict, list[ScrapedComment]]:
    post_info: dict = {}
    comments: list[ScrapedComment] = []
    seen_thread_items: set[int] = set()

    def walk(obj):
        if isinstance(obj, dict):
            if "thread_items" in obj:
                obj_id = id(obj)
                if obj_id not in seen_thread_items:
                    seen_thread_items.add(obj_id)
                    items = obj["thread_items"]
                    if items:
                        # 每個 thread 只取 items[0]，它是這個 thread 的主角
                        post_node = items[0].get("post", {})
                        node_code = post_node.get("code", "")
                        if node_code and node_code == original_post_code:
                            # 這是原始貼文，取 post_info
                            user = post_node.get("user", {})
                            caption = post_node.get("caption") or {}
                            post_info["author"] = user.get("full_name", "")
                            post_info["username"] = user.get("username", "")
                            post_info["content"] = (
                                caption.get("text", "") if isinstance(caption, dict) else str(caption)
                            )
                        elif not original_post_code and not post_info:
                            # 第一個遇到的 thread 視為原始貼文
                            user = post_node.get("user", {})
                            caption = post_node.get("caption") or {}
                            post_info["author"] = user.get("full_name", "")
                            post_info["username"] = user.get("username", "")
                            post_info["content"] = (
                                caption.get("text", "") if isinstance(caption, dict) else str(caption)
                            )
                        else:
                            # 頂層留言（只取 items[0]，忽略 items[1+] 的子回覆）
                            c = _parse_comment_node(post_node)
                            if c:
                                comments.append(c)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return post_info, comments


def _deduplicate(comments: list[ScrapedComment]) -> list[ScrapedComment]:
    seen: set[tuple] = set()
    out: list[ScrapedComment] = []
    for c in comments:
        key = (c.username, c.content[:120])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _run_scrape_in_thread(url: str, on_progress: Optional[ProgressCb] = None) -> ScrapedPost:

    def emit(event: str, payload: dict):
        if on_progress:
            on_progress(event, payload)

    async def _scrape() -> ScrapedPost:
        from playwright.async_api import async_playwright

        post_code = _extract_post_code(url)
        if not post_code:
            raise ValueError(f"無法從 URL 解析 post code：{url}")

        result = ScrapedPost(url=url, post_code=post_code)
        captured_json: list[dict] = []
        seen_keys: set[tuple] = set()

        emit("status", {"msg": "啟動瀏覽器..."})

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="zh-TW",
                viewport={"width": 1280, "height": 900},
            )

            if SESSION_PATH.exists():
                try:
                    data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                    if data.get("cookies"):
                        await context.add_cookies(data["cookies"])
                        emit("status", {"msg": "已載入登入狀態"})
                except Exception:
                    pass

            page = await context.new_page()

            async def handle_response(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if response.status == 200 and "json" in ct:
                        url_lower = response.url.lower()
                        if "graphql" in url_lower or "thread" in url_lower or "comment" in url_lower:
                            body = await response.json()
                            captured_json.append(body)
                            # Parse immediately and emit new comments as they arrive
                            _, new_comments = _parse_threads_json(body, post_code)
                            for c in new_comments:
                                key = (c.username, c.content[:120])
                                if key not in seen_keys:
                                    seen_keys.add(key)
                                    result.comments.append(c)
                                    # 每新增一筆就立即 emit，讓 UI 即時顯示
                                    emit("progress", {
                                        "count": len(result.comments),
                                        "latest": c.author or c.username,
                                        "latest_content": c.content[:40],
                                        "comment": {
                                            "author": c.author,
                                            "username": c.username,
                                            "content": c.content,
                                            "likes": c.likes,
                                            "link": c.link,
                                        },
                                    })
                except Exception:
                    pass

            page.on("response", handle_response)

            emit("status", {"msg": "載入頁面..."})
            # sort_order=recent&filter_type=all 確保撈到全部留言而非 hot 排序
            goto_url = url if "sort_order=" in url else url + ("&" if "?" in url else "?") + "sort_order=recent&filter_type=all"
            await page.goto(goto_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Parse post info AND initial comments from page HTML
            for script in await page.query_selector_all('script[type="application/json"]'):
                try:
                    blob = json.loads(await script.inner_text())
                    post_info, init_comments = _parse_threads_json(blob, post_code)
                    if post_info:
                        result.author = post_info.get("author", result.author)
                        result.content = post_info.get("content", result.content)
                    for c in init_comments:
                        key = (c.username, c.content[:120])
                        if key not in seen_keys:
                            seen_keys.add(key)
                            result.comments.append(c)
                            emit("progress", {
                                "count": len(result.comments),
                                "latest": c.author or c.username,
                                "latest_content": c.content[:40],
                                "comment": {
                                    "author": c.author,
                                    "username": c.username,
                                    "content": c.content,
                                    "likes": c.likes,
                                    "link": c.link,
                                },
                            })
                except Exception:
                    pass

            emit("status", {"msg": "開始滾動撈取留言..."})

            prev_count = 0
            no_new_rounds = 0

            for round_i in range(MAX_SCROLL_ROUNDS):
                await _click_load_more(page)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                # 等頁面網路安靜再算，避免 API 還沒回來就誤判沒有新留言
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                await asyncio.sleep(SCROLL_WAIT)

                current_count = len(result.comments)

                emit("scroll", {
                    "round": round_i + 1,
                    "count": current_count,
                })

                if current_count > prev_count:
                    prev_count = current_count
                    no_new_rounds = 0
                else:
                    no_new_rounds += 1
                    if no_new_rounds >= 6:
                        emit("status", {"msg": "連續 6 次無新留言，完成撈取"})
                        break

            await browser.close()

        result.comments = _deduplicate(result.comments)
        emit("done", {"count": len(result.comments)})
        return result

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_scrape())
    finally:
        loop.close()


async def _click_load_more(page) -> None:
    selectors = [
        'text=查看更多回覆',
        'text=View more replies',
        'text=Show more replies',
        'text=載入更多',
        'text=Load more',
    ]
    for sel in selectors:
        try:
            for btn in await page.locator(sel).all():
                try:
                    if await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass
        except Exception:
            pass



async def scrape_threads_post(url: str, on_progress: Optional[ProgressCb] = None) -> ScrapedPost:
    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(
            pool, _run_scrape_in_thread, url, on_progress
        )
