"""短视频获客内容生产 Agent 工作流 - 命令行入口

用法:
    python main.py check            环境自检(Python/依赖/Ollama/模型/GPU)
    python main.py run [--demo]     跑一次完整管线: 拉热点 -> 生成文案 -> TTS -> 入库
    python main.py agent "任务"     运行 Agent, 让它自己决定调用哪些工具
    python main.py serve            启动 OpenAI 兼容 API 网关 (默认 127.0.0.1:8000)
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台默认 GBK, 强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")

import config


# ---------------- 环境自检 ----------------

def cmd_check() -> None:
    print("=" * 46)
    print("环境自检")
    print("=" * 46)

    # 1. Python 版本
    v = sys.version_info
    print(f"[1/5] Python {v.major}.{v.minor}.{v.micro}", "OK" if v >= (3, 10) else "(建议 >= 3.10)")

    # 2. 依赖
    try:
        import httpx, fastapi, uvicorn, edge_tts, feedparser  # noqa: F401,E401
        print("[2/5] 依赖包导入 OK")
    except ImportError as exc:
        print(f"[2/5] 依赖缺失: {exc} -> 请先 pip install -r requirements.txt")
        return

    # 3. Ollama 服务
    import httpx
    try:
        version = httpx.get(f"{config.OLLAMA_URL}/api/version", timeout=5).json()["version"]
        print(f"[3/5] Ollama 服务 OK (v{version})")
    except Exception:
        print(f"[3/5] Ollama 不可达, 请先启动: ollama serve / 打开 Ollama 应用")
        return

    # 4. 模型
    tags = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=5).json()
    names = [m["name"] for m in tags.get("models", [])]
    if any(n.startswith(config.MODEL_NAME) for n in names):
        print(f"[4/5] 模型 {config.MODEL_NAME} 已就绪")
    else:
        print(f"[4/5] 模型缺失 -> 请执行: ollama pull {config.MODEL_NAME}")
        return

    # 5. GPU 加载状态(模型运行时才会显示)
    try:
        ps = httpx.get(f"{config.OLLAMA_URL}/api/ps", timeout=5).json()
        if ps.get("models"):
            for m in ps["models"]:
                size_vram = m.get("size_vram", 0)
                size = m.get("size", 1)
                pct = size_vram / size * 100 if size else 0
                print(f"[5/5] 当前加载: {m['name']}, 显存占比 {pct:.0f}%")
        else:
            print("[5/5] 暂无运行中的模型(推理时自动加载到 GPU)")
    except Exception:
        print("[5/5] GPU 状态查询失败(不影响运行)")

    print("-" * 46)
    print("自检完成。下一步: python main.py run --demo")


# ---------------- 完整管线 ----------------

def cmd_run(demo: bool, limit: int) -> None:
    from pipeline import fetch, generate, postprocess, storage

    print("=" * 46)
    print(f"完整管线启动 (demo={demo}, limit={limit})")
    print("=" * 46)

    storage.init_db()

    # 1. 拉数据
    topics = fetch.get_topics(limit=limit, demo=demo)

    # 2. 话题入库
    topic_ids = storage.save_topics(topics)
    print(f"[pipeline] {len(topics)} 条话题已入库")

    # 3. 推理生成文案
    copies = postprocess.dedupe(generate.run_batch(topics))

    # 4. 后处理: TTS + 字幕, 并入库
    title2id = dict(zip([t["title"] for t in topics], topic_ids))
    for copy in copies:
        topic_id = title2id.get(copy.get("topic"))
        try:
            paths = postprocess.make_audio(copy.get("hook", "") + "。" + copy.get("body", ""))
            copy.update(paths)
            print(f"[pipeline] 音频/字幕: {Path(paths['audio']).name}")
        except Exception as exc:  # TTS 失败不阻塞入库
            print(f"[pipeline] TTS 失败(跳过): {exc!r}")
        storage.save_copy(copy, topic_id, copy.get("audio", ""), copy.get("subtitle", ""))

    # 5. 汇总
    print("-" * 46)
    print("管线完成! 统计:", json.dumps(storage.stats(), ensure_ascii=False))
    print(f"输出目录: {config.AUDIO_DIR}")
    print(f"数据库:   {config.DB_PATH}")


# ---------------- Agent ----------------

def cmd_agent(task: str, demo: bool) -> None:
    from agent.core import Agent
    print("=" * 46)
    print(f"Agent 启动 (demo={demo})")
    print("=" * 46)
    result = Agent(demo=demo).run(task)
    print("-" * 46)
    print("最终回答:\n", result["final"])
    print(f"工具调用轨迹: {len(result['steps'])} 步")


# ---------------- API 服务 ----------------

def cmd_serve(host: str, port: int) -> None:
    import uvicorn
    from server.api import app
    print(f"OpenAI 兼容网关: http://{host}:{port}/v1")
    print(f"健康检查:       http://{host}:{port}/health")
    uvicorn.run(app, host=host, port=port, log_level="info")


# ---------------- CLI ----------------

def main() -> None:
    parser = argparse.ArgumentParser(description="短视频获客内容生产 Agent 工作流")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="环境自检")

    p_run = sub.add_parser("run", help="跑一次完整管线")
    p_run.add_argument("--demo", action="store_true", help="使用本地数据, 不联网")
    p_run.add_argument("--limit", type=int, default=3, help="拉取话题条数")

    p_agent = sub.add_parser("agent", help="运行 Agent")
    p_agent.add_argument("task", help="给 Agent 的任务描述")
    p_agent.add_argument("--demo", action="store_true", help="离线模式")

    p_serve = sub.add_parser("serve", help="启动 API 网关")
    p_serve.add_argument("--host", default=config.API_HOST)
    p_serve.add_argument("--port", type=int, default=config.API_PORT)

    args = parser.parse_args()
    if args.cmd == "check":
        cmd_check()
    elif args.cmd == "run":
        cmd_run(demo=args.demo, limit=args.limit)
    elif args.cmd == "agent":
        cmd_agent(task=args.task, demo=args.demo)
    elif args.cmd == "serve":
        cmd_serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
