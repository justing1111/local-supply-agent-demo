"""全局配置:路径、模型、API 地址都集中在这里,改一处即可。"""
from pathlib import Path

# ---------- 路径 ----------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "pipeline.db"
FIXTURE_PATH = DATA_DIR / "sample_topics.json"

# ---------- 本地模型 (Ollama) ----------
OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5:7b"          # 7B Q4_K_M 量化版, 约 4.7GB, 8GB 显存可全量跑 GPU
NUM_CTX = 4096                      # 上下文长度, 显存紧张时调小
TEMPERATURE = 0.4                   # 低温度让 JSON 输出更稳定

# ---------- API 服务 ----------
API_HOST = "127.0.0.1"
API_PORT = 8000

# ---------- TTS ----------
TTS_VOICE = "zh-CN-XiaoxiaoNeural"  # edge-tts 免费中文女声


def ensure_dirs() -> None:
    """启动时确保输出目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
