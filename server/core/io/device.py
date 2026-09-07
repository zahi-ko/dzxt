"""音频设备采集与播放（后端独占）。

取舍说明：录音与播放都在 Python 侧完成，前端只负责下发指令与显示。
这样整条处理链路共用同一采样率与 float32 表示，避免浏览器编码格式、
重采样带来的不确定性。
"""

from __future__ import annotations

import threading
import time

import numpy as np
import sounddevice as sd

from server.schemas import DEFAULT_SAMPLE_RATE, SUPPORTED_SAMPLE_RATES, DeviceInfo


# 采样率/设备不被支持时抛出的统一异常，路由层据此转换成友好报错，
# 避免 PortAudio 的原始堆栈直接捅到前端。
class DeviceError(RuntimeError):
    pass


def list_input_devices() -> tuple[list[DeviceInfo], int | None]:
    """枚举可用输入设备。

    返回 (设备列表, 默认设备序号)。设备查询失败时返回空列表而不是抛异常——
    无麦克风只是功能不可用，服务本身仍应正常提供处理与播放能力。
    """
    try:
        devices = sd.query_devices()
    except Exception:  # PortAudio 未初始化或驱动异常
        return [], None

    default_input: int | None = None
    try:
        default = sd.query_devices(kind="input")
        if isinstance(default, dict):
            default_input = int(default.get("index", -1)) or None
    except Exception:
        default_input = None

    items: list[DeviceInfo] = []
    for index, device in enumerate(devices):
        max_inputs = int(device.get("max_input_channels", 0) or 0)
        if max_inputs <= 0:
            continue
        items.append(
            DeviceInfo(
                index=index,
                name=str(device.get("name", f"设备 {index}")),
                channels=max_inputs,
                sample_rate=int(float(device.get("default_samplerate", DEFAULT_SAMPLE_RATE) or 0))
                or DEFAULT_SAMPLE_RATE,
                is_default=(default_input is not None and index == default_input),
            )
        )
    return items, default_input


class Recorder:
    """非阻塞录音器。采集到 float32 数组，供上层转存为 audio_id。"""

    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._started_at: float | None = None
        self._level = 0.0
        self._peak = 0.0
        self._sample_rate = DEFAULT_SAMPLE_RATE
        self._channels = 1
        self._timer: threading.Timer | None = None
        self._auto_stopped = False
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    @property
    def level(self) -> float:
        return self._level

    @property
    def peak(self) -> float:
        return self._peak

    def start(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
        duration: float | None = None,
        device: int | None = None,
    ) -> None:
        if self.recording:
            raise RuntimeError("录音已在进行中")

        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"不支持的采样率: {sample_rate}，可选 {SUPPORTED_SAMPLE_RATES}")

        if channels not in (1, 2):
            raise ValueError(f"不支持的声道数: {channels}，只能为 1 或 2")

        self._chunks = []
        self._level = 0.0
        self._peak = 0.0
        self._auto_stopped = False
        self._sample_rate = sample_rate
        self._channels = channels
        self._started_at = time.monotonic()

        # blocksize=0 交给 PortAudio 自适应缓冲；latency="low" 降低采集延迟。
        # 缓冲过小易产生 glitch（丢帧爆音），故不锁死固定块大小。
        try:
            self._stream = sd.InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                blocksize=0,
                latency="low",
                device=device,
                callback=self._on_data,
            )
            self._stream.start()
        except Exception as exc:  # PortAudioError 类型随驱动版本变化，统一收敛
            self._stream = None
            self._started_at = None
            raise DeviceError(f"无法打开录音设备：{exc}") from exc

        if duration is not None:
            self._timer = threading.Timer(duration, self._auto_stop)
            self._timer.daemon = True
            self._timer.start()

    def _auto_stop(self) -> None:
        """定时录音到点：关闭设备但保留数据，等前端来取。

        若这里直接丢掉数据，前端后续调用 stop 将一无所获，
        因此自动停止与手动停止共用同一份 chunks。
        """
        if not self.recording:
            return

        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        self._close_stream()
        self._auto_stopped = True

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._started_at = None

    def _collect(self) -> tuple[np.ndarray, int]:
        with self._lock:
            if not self._chunks:
                data = np.zeros((0, self._channels), dtype=np.float32)
            else:
                data = np.concatenate(self._chunks, axis=0)
            self._chunks = []

        if self._channels == 1 and data.ndim > 1:
            return data[:, 0], self._sample_rate
        return data, self._sample_rate

    def _on_data(self, indata: np.ndarray, frames: int, time_info, status) -> None:  # noqa: ARG001
        block = indata.astype(np.float32)
        with self._lock:
            self._chunks.append(indata.copy())
        self._level = float(np.sqrt(np.mean(block**2)))
        self._peak = float(np.max(np.abs(block))) if block.size else 0.0

    def stop(self) -> tuple[np.ndarray, int]:
        if self._auto_stopped:
            self._auto_stopped = False
            return self._collect()

        if not self.recording:
            raise RuntimeError("当前没有正在进行的录音")

        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        self._close_stream()
        return self._collect()


class Player:
    """非阻塞播放器。"""

    @staticmethod
    def play(data: np.ndarray, sample_rate: int) -> None:
        sd.play(np.asarray(data, dtype=np.float32), samplerate=sample_rate)

    @staticmethod
    def stop() -> None:
        sd.stop()


_RECORDER = Recorder()
_PLAYER = Player()


def get_recorder() -> Recorder:
    return _RECORDER


def get_player() -> Player:
    return _PLAYER
