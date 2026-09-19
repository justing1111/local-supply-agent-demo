"""ReAct 风格 Agent 核心: 思考 -> 选工具 -> 观察 -> 再思考, 直到给出最终答案。

协议设计说明(踩坑后定的):
    7B 量化模型直接输出 "Thought/Action" 自由文本很容易格式漂移,
    所以改成强制 JSON 协议 + Ollama format="json" 约束:
        {"thought": "...", "action": {"name": "...", "args": {...}}}
        或  {"thought": "...", "final": "最终回答"}
    解析失败就把错误喂回去让它重试, 最多 MAX_STEPS 步强制收敛。
"""
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from pipeline import generate
from agent import tools as toolmod

MAX_STEPS = 8


def _tools_prompt() -> str:
    lines = []
    for name, spec in toolmod.TOOLS.items():
        lines.append(f"- {name}: {spec['desc']} 参数: {json.dumps(spec['args'], ensure_ascii=False)}")
    return "\n".join(lines)


def build_system_prompt() -> str:
    return (
        "你是一个短视频获客内容运营 Agent, 通过调用工具完成用户交给你的任务。\n"
        f"可用工具:\n{_tools_prompt()}\n\n"
        "每一轮你只能输出一个 JSON 对象, 二选一:\n"
        '1) {"thought": "你的思考", "action": {"name": "工具名", "args": {参数}}} \n'
        '2) {"thought": "你的思考", "final": "给用户的最终回答"}\n'
        "规则: 一次只调用一个工具; 任务完成或信息足够时用 final 收尾; "
        "不要编造工具输出; 不要输出 JSON 以外的任何文字。"
    )


def _strip_fence(text: str) -> str:
    """去掉模型偶尔加的 ```json 围栏。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


class Agent:
    def __init__(self, demo: bool = False):
        self.demo = demo
        self.system = build_system_prompt()

    def run(self, task: str) -> dict:
        """执行任务, 返回 {final, steps}。steps 记录每步的工具调用轨迹。"""
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": f"任务: {task}\n(demo={self.demo}, 离线环境请把工具的 demo 参数设为 true)"},
        ]
        trace: list[dict] = []

        for step in range(MAX_STEPS):
            print(f"[agent] 第 {step + 1}/{MAX_STEPS} 步 thinking...")
            raw = generate.chat(messages, json_mode=True)

            try:
                decision = json.loads(_strip_fence(raw))
            except json.JSONDecodeError as exc:
                print(f"[agent] JSON 解析失败, 要求模型重试 ({exc})")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user",
                                 "content": "你的输出不是合法 JSON。重新输出, 只输出一个 JSON 对象, 不要任何其他文字。"})
                continue

            if "final" in decision:
                print("[agent] 任务完成")
                return {"final": decision["final"], "steps": trace}

            action = decision.get("action", {})
            name, args = action.get("name", ""), action.get("args", {})
            print(f"[agent] 调用工具 {name} args={json.dumps(args, ensure_ascii=False)[:120]}")

            if name == "get_hot_topics" and self.demo:
                args.setdefault("demo", True)

            observation = toolmod.run_tool(name, args)
            print(f"[agent] 观察结果: {observation[:150]}")

            trace.append({"step": step + 1, "tool": name, "args": args,
                          "observation": observation[:300]})
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"OBSERVATION: {observation}"})

        return {"final": "已达最大步数仍未完成, 请缩小任务范围后重试。", "steps": trace}


if __name__ == "__main__":
    result = Agent(demo=True).run("从热点里挑一个话题, 生成一条抖音获客文案并存库")
    print(json.dumps(result, ensure_ascii=False, indent=2))
