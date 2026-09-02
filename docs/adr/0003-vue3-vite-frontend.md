# ADR 0003：前端采用 Vue 3 + Vite

- **状态**：已接受（JavaScript 部分已被 [ADR 0005](0005-frontend-typescript.md) 修订为 TypeScript，Vue 3 + Vite 决策不变）
- **日期**：2026-09-02
- **相关**：ADR 0002、AGENT.md 第 3 节

## 背景

初版方案为了降低「每个 session 重搭环境」的成本，倾向零构建的原生 ES Module。重新权衡后推翻该结论。

## 决策

**前端使用 Vue 3 + Vite，JavaScript（不用 TypeScript）。** 独立工程放在 `web/`，开发态由 Vite 代理转发 `/api` 到后端，生产态 `npm run build` 产出 `web/dist` 交由 FastAPI 托管。

## 理由

1. **动态参数表单是本项目 UI 的核心难点。** 效果器由后端注册表动态下发 JSON Schema，前端需据此生成控件并双向绑定。Vue 的 `v-for` + `v-model` 直接解决，原生 JS 要手写 DOM 生成与状态同步，易出 bug。
2. **响应式状态联动。** 录音中禁用按钮、播放指针跟随、波形随参数实时刷新，这类逻辑在 Vue 中是一行绑定，手写则需维护全局状态机。
3. **「界面友好」是题目表明确要求**，组件化更容易做出完整、一致的界面。
4. **代价可控。** 仅多一条 `npm install`，Vite 代理配置约 10 行。相比原生方案增加的复杂度，远小于它省下的 UI 开发量。

## 备选方案

| 方案 | 优点 | 未选原因 |
|---|---|---|
| 原生 ES Module + Canvas | 零构建，无 Node 依赖 | 动态表单与状态联动需手写，UI 质量与开发效率都吃亏 |
| Vue 3 CDN + importmap | 无构建，又有响应式 | 无单文件组件，工程化能力弱，介于两者之间但不彻底 |
| React | 生态更大 | 团队成员若不熟，学习成本高于 Vue；本项目用不到其生态优势 |

## 后果

- 环境多一层 Node 工具链，`web/package-lock.json` 必须入库。
- 约定：所有请求封在 `web/src/api.js`，组件不直接调 `fetch`，保持与后端的单一耦合点。
- 前端一律使用相对路径 `/api/...`，端口由 Vite 代理或后端托管屏蔽。
