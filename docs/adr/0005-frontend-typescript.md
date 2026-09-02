# ADR 0005：前端启用 TypeScript

- **状态**：已接受
- **日期**：2026-09-02
- **相关**：ADR 0003（修订其「不用 TypeScript」部分，Vue 3 + Vite 决策不变）

## 背景

ADR 0003 选定 Vue 3 + Vite 时出于降低上手成本考虑放弃了 TypeScript。重新评估后认为收益被低估：本项目前端大量消费后端动态下发的 JSON Schema（效果器参数表单），类型约束能在编译期拦住字段名拼错、类型不匹配这类隐秘 bug。

## 决策

**前端改用 Vue 3 + TypeScript + Vite（`<script setup lang="ts">`），替换原「原生 JS」表述。**

## 理由

1. **鲁棒性**：类型检查把一批运行时错误提前到编译期，多人协作、跨 session 重建代码时尤其重要。
2. **接口契约对称**：后端已有 Pydantic 契约层（`server/schemas.py`），前端 TS 类型定义是它的镜像，两侧共同锚定同一份接口真相。
3. **代价可控**：Vite 对 TS 是开箱支持，无需额外构建配置；仅需 `tsconfig.json` 与依赖 `typescript` + `vue-tsc`。
4. **IDE 体验**：补全与重构质量显著提升，降低新人接手成本。

## 后果

- `web/` 源码一律 `.ts` / `lang="ts"`，禁止混入裸 `.js` 源文件。
- `web/package.json` 增加依赖：`typescript`、`vue-tsc`；`npm run build` 前先跑类型检查。
- 网络层 `web/src/api.ts` 中为每个接口定义请求/响应类型，与 `server/schemas.py` 保持同步，`schemas.py` 改动时前端类型同步更新。
- `vite.config.ts` 保持 `/api` 代理约定不变。
