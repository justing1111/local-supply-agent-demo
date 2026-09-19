"""数据拉取层: 抓取热点话题。

优先级: 百度热搜 JSON 接口 -> 36kr RSS -> 本地 fixture(离线降级)。
微博热搜接口未登录会 403(需要 cookie), 所以不作为默认源。
任何一层失败都自动降级到下一层, 保证管线在断网时也能演示。
"""
import json
import re
import sys
from pathlib import Path

import feedparser
import httpx

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def fetch_baidu_hot(limit: int = 8) -> list[dict]:
    """百度热搜公开 JSON 接口(无需登录)。

    返回结构是嵌套的: data.cards[*].content[*] 里既有包装块(带 content
    键)也有真实条目(带 word 键), 所以逐层拍平, 只取带 word 的条目。
    """
    r = httpx.get("https://top.baidu.com/api/board?platform=wise&tab=realtime",
                  headers=HEADERS, timeout=10)
    r.raise_for_status()
    cards = r.json()["data"]["cards"]

    items: list[dict] = []
    for card in cards:
        for block in card.get("content", []):
            if "word" in block:          # 本身就是条目
                items.append(block)
            for sub in block.get("content", []):   # 再嵌套一层才是条目
                if isinstance(sub, dict) and "word" in sub:
                    items.append(sub)

    topics = []
    for item in items:
        if item.get("isTop"):
            continue  # 跳过置顶
        topics.append({
            "title": item.get("word", ""),
            "summary": item.get("desc", "") or item.get("word", ""),
            "heat": int(item.get("hotScore", 0) or 0),
            "source": "baidu",
        })
        if len(topics) >= limit:
            break
    return topics[:limit]


def fetch_36kr_rss(limit: int = 8) -> list[dict]:
    """36kr 科技 RSS, 作为百度接口失效时的备选。"""
    feed = feedparser.parse("https://36kr.com/feed", request_headers=HEADERS)
    topics = []
    for entry in feed.entries[:limit]:
        # 去掉摘要里的 HTML 标签
        summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:120]
        topics.append({
            "title": entry.get("title", "").strip(),
            "summary": summary.strip(),
            "heat": 0,
            "source": "36kr",
        })
    if not topics:
        raise RuntimeError("RSS 解析结果为空")
    return topics


def load_fixture() -> list[dict]:
    """本地示例数据, 离线/演示兜底。"""
    data = json.loads(config.FIXTURE_PATH.read_text(encoding="utf-8"))
    return data["topics"]


def get_topics(limit: int = 8, source: str = "auto", demo: bool = False) -> list[dict]:
    """按优先级拉取热点。demo=True 直接用本地数据。

    source: auto | weibo | 36kr | fixture
    """
    if demo:
        print("[fetch] 使用本地 fixture 数据 (demo 模式)")
        return load_fixture()[:limit]

    chain = {
        "baidu": [fetch_baidu_hot],
        "36kr": [fetch_36kr_rss],
        "auto": [fetch_baidu_hot, fetch_36kr_rss],
    }[source]

    for fetcher in chain:
        try:
            topics = fetcher(limit)
            print(f"[fetch] 数据源 {fetcher.__name__} 成功, 拿到 {len(topics)} 条")
            return topics
        except Exception as exc:  # noqa: BLE001 - 逐层降级
            print(f"[fetch] {fetcher.__name__} 失败: {exc!r}, 尝试下一数据源")

    print("[fetch] 全部在线数据源失败, 降级到本地 fixture")
    return load_fixture()[:limit]


if __name__ == "__main__":
    config.ensure_dirs()
    for t in get_topics(5):
        print(f"  [{t['source']}] {t['title']}  heat={t['heat']}")
