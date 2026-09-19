# shortvideo-agent-pipeline

把「刷热点找选题 → 手写文案 → 找配音 → 归档管理」这套短视频获客的人工 SOP,
重做成跑在**本地量化大模型**上的 Agent 工作流。

全程跑在自己的笔记本(RTX 4060 Laptop 8GB)上,推理不走任何云端 API,数据不出本机。

## 架构

```
                     ┌────────────────────────────────────────────┐
                     │              Ollama (GPU)                  │
                     │        qwen2.5:7b  Q4_K_M 量化             │
                     └───────▲────────────────────▲───────────────┘
                             │ /api/chat          │
        ┌────────────────────┴─────┐    ┌─────────┴──────────┐
        │   FastAPI 网关 (OpenAI   │    │   ReAct Agent 循环  │
        │   兼容 /v1/chat/...)     │    │  思考→工具→观察→…   │
        └──────────────────────────┘    └─────────┬──────────┘
                                                  │ 注册工具
   ┌──────────────────────────────────────────────┼─────────────────┐
   │                                              ▼                 │
   │  ┌─────────┐   ┌──────────┐   ┌──────────────┐   ┌─────────┐   │
   │  │ 拉热点   │──▶│ 生成文案  │──▶│ TTS配音+SRT  │──▶│ SQLite  │   │
   │  │ 百度热搜 │   │ 7B 模型  │   │  edge-tts    │   │  入库   │   │
   │  └─────────┘   └──────────┘   └──────────────┘   └─────────┘   │
   │        端到端管线: 拉数据 → 推理 → 后处理 → 入库                  │
   └────────────────────────────────────────────────────────────────┘
```

- **管线模式**:`python main.py run` 一条龙跑完(数据源三级降级,断网也能用本地 fixture 演示)
- **Agent 模式**:`python main.py agent "任务"` 由模型自己决定调哪个工具(选题/写文案/配音/存库)

## 快速开始(Windows)

```powershell
git clone https://github.com/<你的用户名>/shortvideo-agent-pipeline.git
cd shortvideo-agent-pipeline

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 本地量化模型(4.7GB, 首次拉取需要几分钟)
ollama pull qwen2.5:7b

# 环境自检
python main.py check

# 跑一次完整管线(默认拉百度热搜)
python main.py run --limit 2

# 离线演示(不联网, 用本地示例数据)
python main.py run --demo

# Agent 模式: 模型自己决定调用哪些工具
python main.py agent "挑一个热点话题, 生成一条抖音获客文案, 配好音并存进数据库" --demo
```

输出在 `data/` 目录:`pipeline.db`(SQLite)+ `audio/*.mp3` + `audio/*.srt`。

## 对外提供调用(OpenAI 兼容网关)

模型通过 FastAPI 网关暴露成 OpenAI 兼容接口,现有用 OpenAI SDK 的业务代码
只需要改 `base_url` 就能接入本地模型:

```powershell
python main.py serve
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="none")
resp = client.chat.completions.create(
    model="qwen2.5:7b",
    messages=[{"role": "user", "content": "写一句直播开场白"}],
)
print(resp.choices[0].message.content)
```

或者直接 curl:

```powershell
curl http://127.0.0.1:8000/v1/chat/completions -H "Content-Type: application/json" `
  -d '{\"model\": \"qwen2.5:7b\", \"messages\": [{\"role\": \"user\", \"content\": \"hi\"}]}'
```

## 项目结构

```
├── main.py                # CLI: check / run / agent / serve
├── config.py              # 模型、路径、端口等配置
├── pipeline/
│   ├── fetch.py           # 拉热点: 百度热搜 → 36kr RSS → 本地fixture 三级降级
│   ├── generate.py        # 推理: 调 Ollama 生成多平台获客文案(JSON 约束输出)
│   ├── postprocess.py     # 后处理: 文本清洗 + edge-tts 配音 + 词级时间戳转 SRT
│   └── storage.py         # SQLite 入库与统计
├── agent/
│   ├── tools.py           # 工具注册表(拉热点/写文案/配音/存库/查库)
│   └── core.py            # ReAct 循环: 强制 JSON 协议 + 失败重试 + 最大步数
├── server/api.py          # FastAPI OpenAI 兼容网关
└── data/                  # 运行产物(db / mp3 / srt), fixture 示例数据也在
```

## 踩坑记录

记下几个卡住过的地方和解决过程(面试被问就直接讲这些):

1. **edge-tts 7.x 生成的 SRT 字幕是空的**
   升级到 edge-tts 7.2 后,配音正常但字幕文件 0 字节。翻了仓库 changelog 没提,
   直接读 `communicate.py` 源码,发现 7.x 把 `Communicate` 的默认
   `boundary` 从 `WordBoundary` 改成了 `SentenceBoundary`,词级时间戳
   不再默认下发。显式传 `boundary="WordBoundary"` 解决。

2. **微博热搜接口 403**
   本来用微博热搜当数据源,带上浏览器 UA 依然 403,抓包对比发现该接口
   现在必须带登录 cookie,放弃。换成百度热搜公开 JSON 接口,又发现它
   返回结构是嵌套的(`cards[*].content[*]` 里包装块和真实条目混在一起),
   第一次解析只拿到 1 条空标题,逐层打印 JSON 结构后写了个拍平逻辑。

3. **7B 量化模型的 JSON 输出不稳定**
   Agent 每步要求模型输出 JSON,但 7B 模型偶尔会在前后多话或输出不完整。
   解法分三层:Ollama 请求里加 `format: "json"` 强约束;解析失败时把
   报错信息喂回对话让模型自我修正(重试一次);设 `MAX_STEPS=8` 兜底,
   超过就返回可解释的失败而不是死循环。

4. **Windows 控制台 GBK 编码**
   中文输出到 PowerShell 乱码、写文件默认 GBK。统一处理:入口
   `sys.stdout.reconfigure(encoding="utf-8")`,所有 `open` 显式
   `encoding="utf-8"`。

5. **8GB 显存跑 7B 模型**
   选 `qwen2.5:7b`(Q4_K_M 量化,约 4.7GB),`num_ctx` 控制在 4096,
   用 `ollama ps` 确认权重 100% 进显存,推理时不碰 CPU。

## TODO

- [ ] 接入 ffmpeg:音频+字幕自动合成竖屏成片(工具已预留,检测到 ffmpeg 自动注册)
- [ ] 用 ASR(如 faster-whisper)做字幕精确对齐
- [ ] 文案批量任务的队列化与失败重试

## 环境

- Windows 11 + Python 3.13(venv)
- Ollama 0.34 + qwen2.5:7b(Q4_K_M 量化)
- RTX 4060 Laptop 8GB
