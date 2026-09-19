"""推理层: 调用本地 Ollama 量化模型, 把热点话题加工成各平台获客文案。

关键点:
1. 用 Ollama 的 format="json" 强制 JSON 输出, 7B 模型也能稳定解析;
2. 解析失败时带错误信息重试一次, 而不是直接崩掉。
"""
import json
import sys
from pathlib import Path

import httpx

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

TIMEOUT = httpx.Timeout(300.0)  # CPU 推理可能很慢, 超时放宽到 5 分钟


def chat(messages: list[dict], json_mode: bool = False,
         model: str | None = None, temperature: float | None = None) -> str:
    """调用 Ollama /api/chat, 返回模型回复文本。"""
    payload = {
        "model": model or config.MODEL_NAME,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": config.TEMPERATURE if temperature is None else temperature,
            "num_ctx": config.NUM_CTX,
        },
    }
    if json_mode:
        payload["format"] = "json"

    resp = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


# 每个平台的获客文案套路不同, prompt 里把结构写死, 输出质量明显更稳
PLATFORM_PROMPTS = {
    "douyin": (
        "写一条抖音口播短视频文案, 用于给商家获客。要求:"
        "开头 3 秒强钩子, 中间痛点共鸣+解决方案, 结尾引导评论/私信。"
        "口语化, 总字数 150 字以内。"
    ),
    "xiaohongshu": (
        "写一条小红书种草笔记, 用于获客。要求:"
        "标题 20 字以内、有情绪点; 正文分 3-4 个要点, 每点一句话;"
        "结尾给 6 个话题标签(带#)。"
    ),
    "wechat": (
        "写一条公众号文章标题+导语, 用于 B 端获客。要求:"
        "标题制造信息差, 导语 80 字以内点出目标读者和收获。"
    ),
}


def _build_prompt(topic: dict, platform: str) -> str:
    style = PLATFORM_PROMPTS[platform]
    return (
        f"{style}\n\n"
        f"热点话题: {topic['title']}\n"
        f"话题背景: {topic['summary']}\n\n"
        '严格输出 JSON, 字段: {"title": "文案标题", "hook": "开头钩子", '
        '"body": "正文内容", "hashtags": ["话题标签"...]}'
    )


def generate_copy(topic: dict, platform: str = "douyin") -> dict:
    """单个话题 -> 单平台文案, 返回结构化 dict。"""
    if platform not in PLATFORM_PROMPTS:
        raise ValueError(f"不支持的平台: {platform}, 可选 {list(PLATFORM_PROMPTS)}")

    messages = [
        {"role": "system", "content": "你是短视频获客文案专家, 只输出 JSON。"},
        {"role": "user", "content": _build_prompt(topic, platform)},
    ]

    last_err = None
    for attempt in range(2):  # 最多重试一次
        raw = chat(messages, json_mode=True)
        try:
            copy = json.loads(raw)
            copy["platform"] = platform
            copy["topic"] = topic["title"]
            return copy
        except json.JSONDecodeError as exc:
            last_err = exc
            # 把解析错误喂回去, 让模型自己修正输出
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user",
                             "content": f"上面的输出 JSON 解析失败({exc}), 请修正后重新只输出 JSON。"})

    raise RuntimeError(f"文案 JSON 解析连续失败: {last_err}")


def run_batch(topics: list[dict], platforms: list[str] | None = None) -> list[dict]:
    """批量: 每个话题 x 每个平台生成一条文案。"""
    platforms = platforms or ["douyin", "xiaohongshu"]
    results = []
    for i, topic in enumerate(topics, 1):
        for platform in platforms:
            print(f"[generate] ({i}/{len(topics)}) {platform} <- {topic['title'][:20]}")
            try:
                results.append(generate_copy(topic, platform))
            except Exception as exc:  # noqa: BLE001 - 单条失败不拖垮整批
                print(f"[generate] 失败, 跳过: {exc!r}")
    return results


if __name__ == "__main__":
    config.ensure_dirs()
    topic = {"title": "8GB 显存跑通 7B 大模型", "summary": "量化部署实战"}
    import pprint
    pprint.pprint(generate_copy(topic, "douyin"))
