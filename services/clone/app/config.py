"""语音克隆适配层配置。

引擎与适配层解耦：引擎地址、端口都可用环境变量覆盖，
默认值与 AGENT.md §3.4 的启动说明保持一致。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 引入仓库根的 common/ 共享模块（audio_codec 与主干共用同一份实现）。
# services/clone/app/config.py → parents[3] = 仓库根
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

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
