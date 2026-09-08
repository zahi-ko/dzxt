"""适配层参考音频多格式解码测试（services/clone/app/refs.py）。

soundfile 主路径（wav/flac/ogg/opus/mp3 读取）+ ffmpeg 兜底（m4a/aac/wma/webm）。
所有格式最终归一化为 PCM_16 WAV 落盘，引擎侧只面对 wav。

依赖说明：mp3/m4a 用例需要系统或引擎包内有 ffmpeg（CI/本机均已具备），
无 ffmpeg 时自动跳过。
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

# 适配层以独立 venv 运行，但其纯逻辑模块（refs/config）可被主环境直接导入测试
CLONE_DIR = Path(__file__).resolve().parents[1] / "services" / "clone"
sys.path.insert(0, str(CLONE_DIR))

from app.config import REF_MAX_SEC, REF_MIN_SEC, SUPPORTED_EXTENSIONS  # noqa: E402
from app.refs import RefError, RefStore  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None
SR = 32000


def _sine_wav(seconds: float = 6.0) -> bytes:
    t = np.linspace(0, seconds, int(seconds * SR), endpoint=False)
    data = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buf = io.BytesIO()
    import soundfile as sf

    sf.write(buf, data, SR, format="WAV")
    return buf.getvalue()


def _transcode(wav: bytes, codec_args: list[str], format_name: str) -> bytes:
    """借助 ffmpeg 把 WAV 字节转码为其他容器格式（仅测试用）。"""
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", *codec_args, "-f", format_name, "pipe:1"],
        input=wav, capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout


@pytest.fixture()
def store(tmp_path: Path) -> RefStore:
    return RefStore(directory=tmp_path)


# ---------- 受理范围 ----------


def test_supported_extension_set_covers_common_formats() -> None:
    for ext in (".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".webm"):
        assert ext in SUPPORTED_EXTENSIONS


def test_wav_upload_ok(store: RefStore) -> None:
    record = store.add(_sine_wav(), "ref.wav", "你好")
    assert record.duration == pytest.approx(6.0, rel=0.01)
    assert record.sample_rate == SR
    assert (store.directory / f"{record.ref_id}.wav").exists()


def test_duration_below_min_rejected(store: RefStore) -> None:
    with pytest.raises(RefError, match="超出受理范围"):
        store.add(_sine_wav(REF_MIN_SEC - 0.5), "short.wav", "")


def test_duration_above_max_rejected(store: RefStore) -> None:
    with pytest.raises(RefError, match="超出受理范围"):
        store.add(_sine_wav(REF_MAX_SEC + 1.0), "long.wav", "")


def test_unsupported_extension_rejected_with_hint(store: RefStore) -> None:
    with pytest.raises(RefError, match="不支持的音频格式"):
        store.add(b"nothing here", "notes.txt", "")


def test_garbage_bytes_rejected(store: RefStore) -> None:
    with pytest.raises(RefError):
        store.add(b"\x00\x01\x02 not audio at all", "broken.wav", "")


# ---------- soundfile 主路径 ----------


def test_flac_upload_ok(store: RefStore) -> None:
    flac = _transcode(_sine_wav(), ["-c:a", "flac"], "flac")
    record = store.add(flac, "ref.flac", "参考")
    assert record.duration == pytest.approx(6.0, rel=0.05)
    # 落盘后一定是 wav
    assert (store.directory / f"{record.ref_id}.wav").stat().st_size > 0


def test_ogg_upload_ok(store: RefStore) -> None:
    ogg = _transcode(_sine_wav(), ["-c:a", "libvorbis", "-q:a", "4"], "ogg")
    record = store.add(ogg, "ref.ogg", "参考")
    assert record.duration == pytest.approx(6.0, rel=0.1)


# ---------- ffmpeg 兜底路径 ----------


@pytest.mark.skipif(not HAS_FFMPEG, reason="需要 ffmpeg")
def test_aac_upload_via_ffmpeg(store: RefStore) -> None:
    # ipod/mp4 muxer 不支持不可寻址输出，管道转码用 ADTS 裸流（.aac）
    aac = _transcode(_sine_wav(), ["-c:a", "aac", "-b:a", "128k"], "adts")
    record = store.add(aac, "ref.aac", "参考")
    assert record.duration == pytest.approx(6.0, rel=0.1)
    with_ref = store.get(record.ref_id)
    assert with_ref.filename == "ref.aac"


@pytest.mark.skipif(not HAS_FFMPEG, reason="需要 ffmpeg")
def test_m4a_upload_via_ffmpeg(store: RefStore) -> None:
    """m4a（mp4 容器，moov 默认在文件尾）：验证临时文件兜底路径。"""
    wav_path = None
    m4a_path = None
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        wav_path = Path(td) / "in.wav"
        m4a_path = Path(td) / "in.m4a"
        wav_path.write_bytes(_sine_wav())
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-i", str(wav_path), "-c:a", "aac", "-b:a", "128k", str(m4a_path)],
            check=True, capture_output=True,
        )
        record = store.add(m4a_path.read_bytes(), "ref.m4a", "参考")
    assert record.duration == pytest.approx(6.0, rel=0.1)


@pytest.mark.skipif(not HAS_FFMPEG, reason="需要 ffmpeg")
def test_mp3_upload_ok(store: RefStore) -> None:
    mp3 = _transcode(_sine_wav(), ["-c:a", "libmp3lame", "-b:a", "128k"], "mp3")
    record = store.add(mp3, "ref.mp3", "参考")
    assert record.duration == pytest.approx(6.0, rel=0.1)


@pytest.mark.skipif(not HAS_FFMPEG, reason="需要 ffmpeg")
def test_wma_upload_via_ffmpeg(store: RefStore) -> None:
    wma = _transcode(_sine_wav(), ["-c:a", "wmav2", "-b:a", "128k"], "asf")
    record = store.add(wma, "ref.wma", "参考")
    assert record.duration == pytest.approx(6.0, rel=0.1)


@pytest.mark.skipif(not HAS_FFMPEG, reason="需要 ffmpeg")
def test_corrupt_wav_reports_ffmpeg_detail(store: RefStore) -> None:
    """soundfile 解不动的损坏文件，错误信息应来自 ffmpeg 且可读。"""
    with pytest.raises(RefError, match="解码失败"):
        store.add(b"RIFFxxxxWAVEjunk", "corrupt.wav", "")
