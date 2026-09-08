"""语音克隆适配层配置。

引擎与适配层解耦：引擎地址、端口都可用环境变量覆盖，
默认值与 AGENT.md §3.4 的启动说明保持一致。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# GPT-SoVITS 引擎（api_v2.py）地址
ENGINE_BASE_URL = os.environ.get("CLONE_ENGINE_URL", "http://127.0.0.1:9880")

# 适配层自身监听地址
HOST = os.environ.get("CLONE_ADAPTER_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLONE_ADAPTER_PORT", "9900"))

# 参考音频落盘目录（不入库，见根 .gitignore 的 *.wav）
WAVS_DIR = Path(__file__).resolve().parent.parent / "wavs"

# 参考音频时长上下限（秒）。引擎官方建议 5–10s，此处放宽受理区间，
# 合成质量仍取决于参考音本身是否清晰。
REF_MIN_SEC = 2.0
REF_MAX_SEC = 15.0

# 合成单句长度上限（字符）。过长文本引擎侧容易胡言乱语，前端也会引导分段。
TEXT_MAX_CHARS = 500

# 引擎探活与合成的超时（秒）。合成走冷启动时首次可能偏慢，放宽读超时。
HEALTH_TIMEOUT = 3.0
SYNTH_TIMEOUT = (30.0, 300.0)

# 上传受理的音频格式。soundfile(libsndfile) 原生可解的放 SOUNDFILE 格式组；
# 其余（m4a/aac/wma/webm 等）依赖 ffmpeg 兜底解码，最终统一转写为 WAV 落盘。
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".aif", ".aiff",
     ".m4a", ".m4b", ".aac", ".wma", ".webm"}
)

# ffmpeg 查找顺序：环境变量 → 引擎整合包内置 → 系统 PATH。
_FFMPEG_ENV = os.environ.get("CLONE_FFMPEG", "")
_FFMPEG_CANDIDATES = [
    Path(_FFMPEG_ENV) if _FFMPEG_ENV else None,
    Path(os.environ.get("CLONE_ENGINE_DIR", r"C:\Users\zahi\.venvs\GPT-SoVITS-v2pro-20250604"))
    / "runtime" / "bin" / "ffmpeg.exe",
    Path(r"C:\Users\zahi\.venvs\GPT-SoVITS-v2pro-20250604") / "ffmpeg.exe",
]
FFMPEG_PATH: str | None = next(
    (str(p) for p in _FFMPEG_CANDIDATES if p and p.is_file()), None
) or shutil.which("ffmpeg")
