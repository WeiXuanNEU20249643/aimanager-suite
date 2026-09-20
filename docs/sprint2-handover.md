# Sprint 2 交接文档

## 交接结论

Sprint 2 已按三阶段融合版规划完成。现有工程仍是 React + Vite 前端、FastAPI 服务端和 SQLite 数据库；未新建项目，原有导航、布局、颜色与组件体系保持不变。Sprint 3 可在当前真实任务、依赖、排期和成员容量数据之上继续实现甘特图与成员任务图。

本轮 Must：US18、US19、US09、US33、US11、US27、US28、US05。

本轮已排 Should：US07、US21、US30。

详细验收口径见 `docs/sprint2-validation.md`，接口字段和失败语义见 `docs/api-sprint2.md`。

## 已交付能力

| 范围 | 当前结果 | 下轮如何复用 |
| --- | --- | --- |
| 需求版本 | 需求编辑需要版本和原因，旧版本只读；优先级与验收条件入库 | Sprint 3 的需求重排可用需求版本和 `review_required` 标记识别影响任务 |
| 任务依赖与阻塞 | 同项目依赖、循环校验、人工阻塞、操作事件 | 甘特排期直接读取 `dependencies`；计划日期暂不因依赖自动改动 |
| 工时与排期数据 | 估算、实际、剩余工时，计划开始/结束、锁定标记 | 甘特图和成员任务图必须读取同一批任务字段，不另存排期副本 |
| 成员容量 | 周容量、可用时段、技能标签、容量版本 | Sprint 3 排期校验读取成员容量；不要用任务数量代替工作量 |
| 任务历史 | 只读事件、前后值、操作者、时间、原因、历史缺口提示 | 用于追溯甘特/成员图变化；禁止补造或覆盖历史 |
| 取消与重开 | 取消保留最后状态并退出有效分母；已完成可重开为进行中 | 图表默认排除取消任务；已完成或排期锁定任务不得静默移动 |
| 状态与完成率 | 四状态、取消单列、同口径筛选、完成率和本周重开数 | Sprint 3 不应改变现有完成率与取消口径 |

## 数据模型与迁移

数据库当前程序支持 `PRAGMA user_version=3`。启动服务或执行 `python -m app.manage migrate` 会将旧库增量升级。

- schema 1：账号、项目、需求、任务、会话、事件。
- schema 2：需求版本、优先级、验收条件、任务依赖、里程碑、候选自定义角色、取消预留字段。
- schema 3：`tasks` 的工时/计划字段，以及 `member_capacities`。

已在正式库副本验证 v1 → v3，并重复执行迁移：用户、项目、需求、任务和事件数量保持一致。不要直接覆盖 `backend/data/aimanager.sqlite3`；如需升级，先备份后运行迁移。

任务排期关键字段：

```text
estimated_hours, actual_hours, remaining_hours
planned_start, planned_end, due_date, plan_locked
```

成员容量关键字段：

```text
weekly_capacity_hours, available_from, available_to, skill_tags
```

## 关键接口

| 接口 | 用途 | Sprint 3 注意点 |
| --- | --- | --- |
| `GET /projects/{id}/tasks` | 支持 `q`、`owner_id`、`status`、`cancelled` 查询真实任务 | 甘特与成员图用项目作用域查询；`cancelled=active` 是默认口径 |
| `PATCH /tasks/{id}/plan` | 更新工时、计划日期、锁定标记，带 `version` | 更新前检查版本；结束日期不得早于开始日期 |
| `GET /projects/{id}/members` | 返回成员及容量、技能数据 | 无容量记录会明确返回空值和 `capacity_version: 0` |
| `PATCH /members/{id}/capacity` | 更新容量、可用期、技能，带容量版本 | 仅有效项目成员；避免跨项目复用成员数据 |
| `POST /tasks/{id}/dependencies` | 新增前置依赖 | 已拒绝循环；自动排期规则应建立在此结果上 |
| `GET /tasks/{id}/history` | 只读事件历史 | 历史缺口用 `missing_records` 暴露，不能按快照补写 |
| `GET /statistics/completion` | 状态、完成率、取消数、本周重开数 | 当前列表筛选会影响概览；趋势口径需另行明确，不要静默复用筛选 |

所有写请求需要同源会话和 `X-Requested-With: aimanager`。前端应继续只通过 `frontend/src/api.js` 发请求。

## 权限与状态约束

- 所有请求按当前项目成员关系重新鉴权；不要缓存权限到前端或会话。
- 内置管理员独占最终验收、取消、重开、成员和角色管理。
- 取消任务不能编辑、流转、改绑来源、更新排期、维护阻塞或依赖，也不能恢复取消。
- 重开只允许未取消的已完成任务，必须附原因，转换为“进行中”。
- 事件表只追加，数据库触发器拒绝更新或删除事件。
- 所有带 `version` 的更新冲突返回 409；前端应刷新后让用户重新确认。

## UI 与代码入口

| 区域 | 文件 | 当前职责 |
| --- | --- | --- |
| API 适配层 | `frontend/src/api.js` | 唯一网络入口，统一 Cookie、请求头与错误处理 |
| 任务页 | `frontend/src/sprint1/Tasks.jsx` | 看板/列表、组合筛选、任务详情、工时排期、取消/重开、历史 |
| 概览页 | `frontend/src/sprint2/Overview.jsx` | 真实状态概览、里程碑、成员容量与技能 |
| 后端 API | `backend/app/main.py` | 鉴权、业务规则、事件、统计接口 |
| 数据库迁移 | `backend/app/db.py` | schema 1 至 3 的增量迁移 |
| 输入校验 | `backend/app/schemas.py` | 工时、日期、容量、原因、版本等约束 |

继续沿用 `frontend/src/components.jsx`、`frontend/src/styles.css` 与 `frontend/src/sprint1/styles.css`。不要把甘特图或成员任务图改为 Mock 数据页面；应在现有路由对应组件中替换预览数据。

## 保留的候选功能

以下能力来自前一轮实现，在融合版规划中未排入本轮 Must，但已保留且可复用：

- US10：里程碑关联及完成率。
- US20：带原因和事件的任务源需求改绑。
- US22、US23、US25：自定义角色、模块权限和即时生效的角色分配。

它们不应被删除或计入 Sprint 2 Must；Sprint 3 改动需保证这些已有接口继续回归通过。

## Sprint 3 接手顺序

1. 阅读融合版规划中的 US34、US35、US36、US37 及验收条件，确认本轮只做三视图联动。
2. 在后端先定义共享任务查询、排期版本和日期重算规则；复用任务 ID、`version`、依赖、工时、计划日期、锁定和取消标记。
3. 先实现甘特图真实读取与未排期任务提示，再实现成员任务图；两图和看板不得维护各自的任务副本。
4. 实现需求变更后的受影响未开始任务重排；已完成或 `plan_locked=true` 的任务不可静默移动，必须记录原因和前后值。
5. 每个模块完成后依次运行后端单元测试、`npm run build`、Sprint 1 浏览器回归和新增 Sprint 3 浏览器流程。

## 当前验证结果

```powershell
cd E:\A_DevManage\aimanager-suite\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm run build
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e:sprint2
```

最后一次验证结果：后端 25 组测试通过，前端构建通过，Sprint 1 和 Sprint 2 浏览器流程均通过。浏览器测试使用临时 SQLite，不会修改正式库；截图位于忽略目录 `artifacts/`。

## 尚需人工完成的事项

- 由非作者按 `docs/sprint2-validation.md` 的人工复演步骤独立验收。
- 产品负责人确认八条 Must 和三条 Should 的接受结论。
- 升级真实演示库前先备份，再执行迁移并记录升级时间、操作者和结果。
- 当前目录没有 Git 元数据、远端 CI 或 PR；如后续接入版本库，需要补充提交、分支和 CI 证据。
