# services/clone/ · 语音克隆子服务

必做的拓展功能：本地 GPT-SoVITS。

- **独立虚拟环境**：Python 3.11 + PyTorch + CUDA，与主干隔离，单独 `pyproject.toml` / venv
- **通信方式**：HTTP。主干通过 `TTSProvider` 抽象层对接（云端实现插槽留好，当前不实现）
- 本目录**不提交模型权重**，权重走 `scripts/download_models.py` 下载

## 目标接口（待实现）

上传参考音频 → 提交文本 → 返回合成音频。

架构决策见 `docs/adr/0004-voice-clone-local.md`。
