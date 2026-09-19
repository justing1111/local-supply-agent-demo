"""Agent 可用工具集。

每个工具是一个普通 Python 函数, 注册到 TOOLS 表里:
    名字 -> {"desc": 给模型看的说明, "args": 参数说明, "func": 真正执行}
模型通过 JSON 指定 action, Agent 循环在这里查找并执行, 再把结果喂回去。
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from pipeline import fetch, generate, postprocess, storage


# ---------------- 工具实现 ----------------

def tool_get_hot_topics(limit: int = 5, demo: bool = False) -> str:
    """拉取当前热点话题。demo=True 时用本地数据(离线可用)。"""
    topics = fetch.get_topics(limit=max(1, min(int(limit), 10)), demo=demo)
    return json.dumps([{k: t[k] for k in ("title", "summary", "heat")}
                       for t in topics], ensure_ascii=False)


def tool_generate_copy(topic_title: str, topic_summary: str = "",
                       platform: str = "douyin") -> str:
    """针对一个话题生成指定平台的获客文案(douyin/xiaohongshu/wechat)。"""
    copy = generate.generate_copy(
        {"title": topic_title, "summary": topic_summary}, platform)
    return json.dumps(copy, ensure_ascii=False)


def tool_make_audio(text: str, filename: str = "") -> str:
    """把文案转成配音 mp3 + SRT 字幕, 返回文件路径。"""
    paths = postprocess.make_audio(text, filename or None)
    return json.dumps(paths, ensure_ascii=False)


def tool_save_result(topic_title: str, platform: str, title: str,
                     hook: str = "", body: str = "",
                     hashtags: list[str] | None = None) -> str:
    """把生成好的文案存入数据库。"""
    copy_id = storage.save_copy({
        "topic": topic_title, "platform": platform, "title": title,
        "hook": hook, "body": body, "hashtags": hashtags or [],
    })
    return f"已入库, copies.id={copy_id}"


def tool_db_stats() -> str:
    """查询数据库统计: 已存话题数、文案数、各平台分布。"""
    return json.dumps(storage.stats(), ensure_ascii=False)


# ffmpeg 是可选项: 装了才注册这个工具
def tool_make_video(mp3_path: str, srt_path: str, out_name: str = "output.mp4") -> str:
    """(可选) 用 ffmpeg 把音频+字幕封装成视频(纯色底)。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return "ERROR: 未安装 ffmpeg, 跳过视频合成"
    import subprocess
    out = config.AUDIO_DIR / out_name
    cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=10",
           "-i", mp3_path, "-vf", f"subtitles={srt_path}", "-shortest", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return f"视频已生成: {out}"


# ---------------- 注册表 ----------------

TOOLS = {
    "get_hot_topics": {
        "desc": "拉取当前热点话题列表, 用于选题。demo=True 用本地数据。",
        "args": {"limit": "int, 条数, 默认5", "demo": "bool, 离线模式"},
        "func": tool_get_hot_topics,
    },
    "generate_copy": {
        "desc": "根据话题生成指定平台的获客文案, 返回 JSON(title/hook/body/hashtags)。",
        "args": {"topic_title": "str", "topic_summary": "str",
                 "platform": "douyin|xiaohongshu|wechat"},
        "func": tool_generate_copy,
    },
    "make_audio": {
        "desc": "把文案正文转成配音 mp3 和 SRT 字幕。",
        "args": {"text": "str", "filename": "str, 可选"},
        "func": tool_make_audio,
    },
    "save_result": {
        "desc": "把最终文案保存进数据库。",
        "args": {"topic_title": "str", "platform": "str", "title": "str",
                 "hook": "str", "body": "str", "hashtags": "list[str]"},
        "func": tool_save_result,
    },
    "db_stats": {
        "desc": "查看数据库统计信息。",
        "args": {},
        "func": tool_db_stats,
    },
    "make_video": {
        "desc": "(可选) 音频+字幕合成竖屏视频, 需要本机安装 ffmpeg。",
        "args": {"mp3_path": "str", "srt_path": "str", "out_name": "str"},
        "func": tool_make_video,
    },
}


def run_tool(name: str, args: dict) -> str:
    """安全执行工具: 任何异常都转成字符串观察结果, 不让 Agent 循环崩掉。"""
    if name not in TOOLS:
        return f"ERROR: 未知工具 {name}, 可用工具: {list(TOOLS)}"
    try:
        return str(TOOLS[name]["func"](**args))
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {type(exc).__name__}: {exc}"


if __name__ == "__main__":
    # 快速自测
    print(run_tool("db_stats", {}))
