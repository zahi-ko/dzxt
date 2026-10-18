"""语音加噪与降噪子服务配置。

与 clone 适配层同构：地址、端口、体积上限均可用环境变量覆盖，
默认值与 AGENT.md §3.5 的启动说明保持一致。
"""

from __future__ import annotations

import os

# 子服务自身监听地址
HOST = os.environ.get("NOISE_ADAPTER_HOST", "127.0.0.1")
PORT = int(os.environ.get("NOISE_ADAPTER_PORT", "9910"))

# 上传体积上限（字节）。加噪/谱减都是 O(n) 级纯计算，限制仅防误传超大文件。
MAX_UPLOAD_BYTES = int(os.environ.get("NOISE_MAX_UPLOAD_MB", "100")) * 1024 * 1024
