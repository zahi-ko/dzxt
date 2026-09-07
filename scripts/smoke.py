"""提交前冒烟脚本：跑通一条完整业务链路。

与 pytest 的分工：
- pytest 负责逐条断言（算法正确性、异常分支）
- 本脚本负责端到端串一遍真实接口，确保「链路还在」而不是「每个零件还在」

用法（提交前与 pytest 一起跑，见 AGENT.md 第 8 节）：
    uv run python scripts/smoke.py

退出码 0 表示通过，1 表示有步骤失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 直接 `python scripts/smoke.py` 时 sys.path[0] 是 scripts/，
# 需要把仓库根加回来才能 import server（pytest 那边由 pythonpath 配置解决）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server.core.effects  # noqa: E402,F401  触发效果器注册
from server.core.io.audio_file import dump_audio
from server.main import app

SAMPLE_RATE = 16000


def synthetic_speech(seconds: float = 1.0) -> np.ndarray:
    """类语音激励：带停顿的谐波串，比纯正弦更接近真实录音。"""
    length = int(seconds * SAMPLE_RATE)
    timeline = np.arange(length) / SAMPLE_RATE
    envelope = ((np.arange(length) // int(0.15 * SAMPLE_RATE)) % 2 == 0).astype(np.float32)

    signal = np.zeros(length, dtype=np.float32)
    for harmonic in (1, 2, 3, 5):
        signal += (0.25 / harmonic) * np.sin(2 * np.pi * 300 * harmonic * timeline).astype(
            np.float32
        )
    return (signal * envelope).astype(np.float32)


def main() -> int:
    client = TestClient(app)
    failed: list[str] = []

    def check(step: str, condition: bool, detail: str = "") -> None:
        status = "OK  " if condition else "FAIL"
        print(f"[{status}] {step}{(' — ' + detail) if detail else ''}")
        if not condition:
            failed.append(step)

    # 1. 服务健康
    health = client.get("/api/health")
    check("健康检查", health.status_code == 200, f"effects={health.json().get('effects')}")

    # 2. 采集替代：上传合成音频
    payload = dump_audio(synthetic_speech(1.0), SAMPLE_RATE)
    upload = client.post("/api/audio/upload", files={"file": ("smoke.wav", payload, "audio/wav")})
    check("上传音频", upload.status_code == 200)
    if upload.status_code != 200:
        return 1
    audio_id = upload.json()["audio_id"]

    # 3. 显示：波形 / 频谱 / 语谱图 / 统计
    peaks = client.get(f"/api/audio/{audio_id}/peaks?points=500")
    check("波形包络", peaks.status_code == 200 and peaks.json()["points"] == 500)

    spectrum = client.post("/api/analysis/spectrum", json={"audio_id": audio_id, "n_fft": 1024})
    check("频谱", spectrum.status_code == 200 and len(spectrum.json()["freqs"]) == 513)

    spectrogram = client.post(
        "/api/analysis/spectrogram", json={"audio_id": audio_id, "n_fft": 512, "max_frames": 120}
    )
    body = spectrogram.json() if spectrogram.status_code == 200 else {}
    check(
        "语谱图",
        spectrogram.status_code == 200 and len(body.get("data", [])) == body.get("frames", 0) * body.get("bins", 0),
    )

    stats = client.get(f"/api/analysis/{audio_id}/stats")
    check("音频统计", stats.status_code == 200 and stats.json()["duration"] > 0)

    # 4. 处理：效果链
    chain = client.post(
        "/api/effects/chain",
        json={
            "audio_id": audio_id,
            "steps": [
                {"effect": "denoise", "params": {"strength": 1.0}},
                {"effect": "normalize", "params": {"peak_db": -3.0}},
            ],
        },
    )
    check("效果链", chain.status_code == 200, " → ".join(chain.json().get("applied", [])))
    if chain.status_code != 200:
        return 1
    processed = chain.json()["audio_id"]

    # 5. 处理历史与撤销
    history = client.get(f"/api/effects/{processed}/history")
    check(
        "处理历史",
        history.status_code == 200
        and history.json()["root_id"] == audio_id
        and len(history.json()["steps"]) == 2,
    )

    undo = client.post("/api/effects/undo", json={"audio_id": processed})
    check("撤销", undo.status_code == 200 and undo.json()["audio_id"] == audio_id)

    # 6. 播放与导出
    stream = client.get(f"/api/audio/{processed}/stream")
    check("播放流", stream.status_code == 200 and stream.content[:4] == b"RIFF")

    download = client.get(f"/api/audio/{processed}/download")
    check("导出 WAV", download.status_code == 200 and download.content[:4] == b"RIFF")

    print()
    if failed:
        print(f"冒烟失败 {len(failed)} 项：{', '.join(failed)}")
        return 1
    print("冒烟通过：采集 → 显示 → 处理 → 历史 → 播放/导出 全链路正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
