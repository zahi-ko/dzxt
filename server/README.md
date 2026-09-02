# server/ · 后端（FastAPI）

Python 3.11 + FastAPI + Pydantic v2。接口契约、目录职责见根目录 `AGENT.md` §4–§5。

## 目标结构（待实现）

```
server/
├── main.py           FastAPI 入口 + web/dist 静态托管
├── schemas.py        【契约层】Pydantic 模型，唯一接口真相源，改动必须全组同步
├── session_store.py  audio_id 句柄仓库（内存态）
├── api/
│   ├── deps.py       路由公共依赖（句柄不存在 → 404）
│   └── routers/
│       ├── audio.py     /api/audio  列表、上传、录音起停、播放、下载、删除
│       ├── effects.py   /api/effects 效果清单、施加效果
│       └── analysis.py  /api/analysis 频谱
└── core/
    ├── registry.py   效果器注册表（新效果 = 一个文件 + 一个纯函数）
    ├── effects/      处理算法，一个效果一个文件
    ├── analysis/     频谱与波形包络
    └── io/           录音播放、文件读写
```

## 三条铁律（实现时不得违反）

1. 内部音频表示唯一：`(np.ndarray[float32], sample_rate: int)`，值域 `[-1, 1]`
2. audio_id 句柄制：API 只传 `audio_id`，不传波形
3. 效果器注册表：新算法只写一个文件、一个纯函数，不改路由与前端

完整定义见 `AGENT.md` §4「数据契约」。
