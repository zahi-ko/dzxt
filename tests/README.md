# tests/ · pytest

优先覆盖 Core 层纯函数（效果器、分析、I/O 的可测部分）。

提交前必须通过：

```bash
uv run ruff check .
uv run pytest
```

建议命名：`test_effects.py`、`test_analysis.py`、`test_api.py`（API 走 httpx + TestClient）。
