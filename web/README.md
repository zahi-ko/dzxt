# web/ · 前端（Vue 3 + TypeScript + Vite）

组件化 + 响应式，TypeScript 类型约束（ADR 0005）。所有网络请求封在 `src/api.ts`（唯一后端耦合点），组件不直接调用 fetch/axios。

## 目标结构（待实现）

```
web/
├── index.html
├── vite.config.ts    /api 代理到 127.0.0.1:8000，前端一律写相对路径 /api/...
├── tsconfig.json
└── src/
    ├── main.ts
    ├── App.vue          状态中枢（<script setup lang="ts">）
    ├── api.ts           【唯一后端耦合点】接口类型定义镜像 server/schemas.py
    └── components/
        ├── RecorderCard.vue    采集
        ├── AudioLibrary.vue    列表
        ├── WaveformCanvas.vue  波形
        ├── SpectrumCanvas.vue  频谱
        └── EffectPanel.vue     效果面板（表单由 GET /api/effects 的 JSON Schema 驱动）
```

## 约定

- 源码一律 `.ts` / `<script setup lang="ts">`，禁止混入裸 `.js` 源文件
- `api.ts` 中为每个接口定义请求/响应类型，`server/schemas.py` 改动时同步更新
- `npm run build` 前先跑 `vue-tsc` 类型检查
- 接口优先：schema 与返回 mock 的 router stub 先行，前端可不等后端实现并行开工
- 构建产物 `web/dist/` 由后端托管，不入库

## 依赖

`typescript`、`vue-tsc`（类型检查）；`package-lock.json` 必须入库。
