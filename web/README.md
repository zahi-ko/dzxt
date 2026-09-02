# web/ · 前端（Vue 3 + Vite，原生 JS）

组件化 + 响应式。所有网络请求封在 `src/api.js`（唯一后端耦合点），组件不直接调用 fetch/axios。

## 目标结构（待实现）

```
web/
├── index.html
├── vite.config.js    /api 代理到 127.0.0.1:8000，前端一律写相对路径 /api/...
└── src/
    ├── main.js
    ├── App.vue          状态中枢
    ├── api.js           【唯一后端耦合点】
    └── components/
        ├── RecorderCard.vue    采集
        ├── AudioLibrary.vue    列表
        ├── WaveformCanvas.vue  波形
        ├── SpectrumCanvas.vue  频谱
        └── EffectPanel.vue     效果面板（表单由 GET /api/effects 的 JSON Schema 驱动）
```

## 约定

- 接口优先：schema 与返回 mock 的 router stub 先行，前端可不等后端实现并行开工
- 构建产物 `web/dist/` 由后端托管，不入库
