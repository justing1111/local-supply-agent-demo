"""后处理层: 文本清洗 + TTS 配音 + SRT 字幕生成。

edge-tts 是微软 Edge 浏览器"大声朗读"接口的封装, 免费、无需 API key。
配音时顺便收集 WordBoundary(每个词的时间戳), 直接拼出 SRT 字幕,
不用再跑一遍 ASR 对齐。
"""
import asyncio
import hashlib
import re
import sys
from pathlib import Path

import edge_tts

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config


def clean_text(text: str) -> str:
    """去掉模型输出里常见的 markdown 符号, TTS 读起来更自然。"""
    text = re.sub(r"[#*_`>\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fmt_ts(seconds: float) -> str:
    """SRT 时间戳: 00:00:01,250"""
    ms = int(seconds * 1000)
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(boundaries: list[dict]) -> str:
    """把词级时间戳聚合成每行约 12 字的字幕。offset/duration 单位是 100ns。"""
    lines, cur, cur_start = [], "", None
    for b in boundaries:
        if cur_start is None:
            cur_start = b["offset"]
        cur += b["text"]
        if len(cur) >= 12 or b is boundaries[-1]:
            start = cur_start / 1e7
            end = (b["offset"] + b["duration"]) / 1e7
            lines.append((start, end, cur.strip()))
            cur, cur_start = "", None
    out = []
    for i, (start, end, text) in enumerate(lines, 1):
        out.append(f"{i}\n{_fmt_ts(start)} --> {_fmt_ts(max(end, start + 0.2))}\n{text}\n")
    return "\n".join(out)


async def _tts(text: str, mp3_path: Path, srt_path: Path, voice: str) -> None:
    # 注意: edge-tts 7.x 默认 boundary 变成了 SentenceBoundary,
    # 想拿词级时间戳必须显式指定 WordBoundary, 否则生成的 SRT 是空的
    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    boundaries: list[dict] = []
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                boundaries.append(chunk)
    srt_path.write_text(_build_srt(boundaries), encoding="utf-8")


def make_audio(text: str, filename: str | None = None,
               voice: str | None = None) -> dict:
    """文本 -> mp3 + srt。返回文件路径。"""
    config.ensure_dirs()
    if filename is None:
        filename = hashlib.md5(text.encode()).hexdigest()[:10]
    mp3_path = config.AUDIO_DIR / f"{filename}.mp3"
    srt_path = config.AUDIO_DIR / f"{filename}.srt"
    asyncio.run(_tts(clean_text(text), mp3_path, srt_path, voice or config.TTS_VOICE))
    return {"audio": str(mp3_path), "subtitle": str(srt_path)}


def dedupe(copies: list[dict]) -> list[dict]:
    """按标题去重, 生成阶段偶尔会产出重复内容。"""
    seen, result = set(), []
    for c in copies:
        key = hashlib.md5(c.get("title", "").encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


if __name__ == "__main__":
    config.ensure_dirs()
    paths = make_audio("8GB 显存也能跑通 70 亿参数大模型, 量化部署是关键。", "demo")
    print(paths)
