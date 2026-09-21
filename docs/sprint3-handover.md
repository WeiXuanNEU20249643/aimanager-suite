# Sprint 3 交接文档

## 交接结论

Sprint 3 的 US34、US35、US36、US37 已在现有 React + FastAPI + SQLite 工程中完成。看板、甘特和成员任务图围绕同一任务记录运行；需求确认可触发服务端原子重排；已完成、进行中、待验收或锁定任务不会被静默移动。Sprint 4 可直接复用统一任务 ID、需求编号、依赖、计划日期、任务版本和项目排期版本，继续实现 UML 用例图与时序图。

## 关键入口

| 区域 | 文件 | 当前职责 |
| --- | --- | --- |
| 统一排期规则 | `backend/app/planning.py` | 影响传播、依赖排序、容量折算、重排计算、成员负荷和共享快照 |
| API 与事务 | `backend/app/main.py` | 项目授权、版本校验、原子应用、排期记录和任务事件 |
| 数据库迁移 | `backend/app/db.py` | schema 4 的项目排期版本与重排记录 |
| 甘特图 | `frontend/src/sprint3/Gantt.jsx` | 真实日期、依赖、任务链接、未排期和取消口径 |
| 成员任务图 | `frontend/src/sprint3/MemberTasks.jsx` | 成员分组、工作量/容量、筛选和 5 秒同步 |
| 需求影响入口 | `frontend/src/sprint1/Requirements.jsx` | 影响清单、管理员确认、最近排期结果和冲突 |
| 共享前端逻辑 | `frontend/src/sprint3/shared.js` | 排期读取、静默轮询、日期和工时换算 |

## Sprint 4 复用约束

- UML 页面继续通过 `frontend/src/api.js` 调用真实接口，不从 `mock.js` 复制任务或需求。
- 用例图应使用当前项目的结构化角色、需求/故事编号和关联任务 ID；时序图使用显式参与者与消息顺序，不从甘特日期推断接口调用。
- 看板、甘特、成员图和 UML 的跳转应保留相同 `REQ-ID`、`T-ID` 和项目作用域。
- 新增 UML 表和接口采用 schema 5 增量迁移，不覆盖 schema 4 的排期版本、运行记录或 append-only 事件。
- Sprint 4 改动后必须回归 `npm run test:e2e:sprint3`，确认 5 秒同步、锁定保护和三视图一致性仍然成立。

## 已验证命令

```powershell
cd E:\A_DevManage\aimanager-suite\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm run build
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e:sprint2
$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:e2e:sprint3
```

详细接口见 `docs/api-sprint3.md`，验收证据与人工复演见 `docs/sprint3-validation.md`。
