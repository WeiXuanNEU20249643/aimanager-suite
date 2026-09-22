# Sprint 4 交接文档

## 交接结论

Sprint 4 的 US38、US39 已在现有 React、FastAPI 和 SQLite 工程中完成。UML 中心从真实故事角色、需求、任务和显式交互步骤生成用例图与时序图，生成版本只追加保存；非法场景不会覆盖最近有效结果。按项目规划退出条件，US40、US12、US13 三条 Should 未提前实现，Sprint 3 回归已通过。

## 关键入口

| 区域 | 文件 | 当前职责 |
| --- | --- | --- |
| UML 映射与版本读取 | `backend/app/uml.py` | 用例覆盖映射、时序渲染数据、场景与最近生成版本读取 |
| API 与事务 | `backend/app/main.py` | UML 权限、来源版本校验、场景校验、原子保存和只追加事件 |
| 输入契约 | `backend/app/schemas.py` | 故事角色、参与者、消息、条件分支、任务来源和生成版本 |
| 数据库迁移 | `backend/app/db.py` | schema 5 的故事角色、场景和 UML 生成版本 |
| UML 页面 | `frontend/src/sprint4/UML.jsx` | 真实用例图、时序图、来源链接、场景维护和重新生成 |
| UML 样式 | `frontend/src/sprint4/styles.css` | 角色与用例布局、参与者生命线、消息和条件分支 |
| 回归流程 | `scripts/e2e-sprint4.mjs` | 两个核心场景、来源变化、错误保护、权限与项目隔离 |

## Sprint 5 复用约束

- AI 功能继续通过 `frontend/src/api.js` 调用真实服务，不能把 Sprint 4 的 UML 生成伪装为 AI 调用。
- AI 输入如引用需求、任务或 UML 场景，应保存稳定 `REQ-ID`、`T-ID`、场景 ID、输入版本、模型标识和处置结果。
- AI 建议默认草案，失败或否决不能修改需求、任务、排期、场景或 UML 生成版本。
- schema 6 必须增量迁移，不覆盖 schema 5 的 `story_role`、`uml_scenarios`、`uml_generations` 或 append-only 事件。
- Sprint 5 改动后必须回归 `npm run test:e2e:sprint3` 与 `npm run test:e2e:sprint4`，确认共享任务数据、5 秒同步、UML 来源追溯和旧有效版本保护仍成立。

## 已验证命令

```powershell
cd E:\A_DevManage\aimanager-suite\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm run build
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e:sprint2
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e:sprint3
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e:sprint4
```

接口契约见 `docs/api-sprint4.md`，验收证据与人工复演见 `docs/sprint4-validation.md`。
