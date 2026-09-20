# Sprint 1 API 契约

前缀 `/api`，JSON 字段使用 snake_case；内部角色为 `admin | member | observer`，任务状态为 `待办 | 进行中 | 待验收 | 已完成`，Sprint 为 `S1`—`S6`。请求通过同源 Cookie 认证；写请求需要 `X-Requested-With: aimanager`。参数错误统一返回 422，错误响应不会回显凭据。

| 方法 | 路径 | 权限与返回 |
| --- | --- | --- |
| GET | `/health` | 无需登录；SQLite 连通与 schema_version |
| POST | `/auth/login` | username、password；返回 id、username、name，设置 Cookie |
| GET | `/auth/me` | 有效会话；返回当前账号 |
| POST | `/auth/logout` | 删除当前会话；204，幂等 |
| GET | `/projects` | 当前账号有效成员关系对应的项目及 role |
| GET | `/projects/{project_id}` | 本项目成员；id、name、当前 role |
| GET | `/projects/{project_id}/members` | 本项目成员；有效成员及内置角色 |
| POST | `/projects/{project_id}/members` | 管理员；username、role；201 |
| PATCH | `/projects/{project_id}/members/{user_id}` | 管理员；role；200 |
| DELETE | `/projects/{project_id}/members/{user_id}` | 管理员；软移除；204 |
| GET | `/projects/{project_id}/requirements?q=关键词` | 本项目成员；编号、标题、描述、来源检索，数组 |
| POST | `/projects/{project_id}/requirements` | 管理员／成员；title、description、source；201 |
| GET | `/projects/{project_id}/requirements/{req_id}` | 本项目成员；稳定编号详情 |
| GET | `/projects/{project_id}/tasks` | 本项目成员；任务数组，列表／看板共用 |
| POST | `/projects/{project_id}/tasks` | 管理员／成员；关联同项目源需求；201 |
| GET | `/projects/{project_id}/tasks/{task_id}` | 本项目成员；任务详情 |
| PATCH | `/projects/{project_id}/tasks/{task_id}` | 管理员／成员；完整编辑字段及当前 version |
| PATCH | `/projects/{project_id}/tasks/{task_id}/status` | 管理员／成员；status、version、可选 reason；最终验收限管理员 |

原 `/project`、`/requirements`、`/tasks`、`/ai/analysis` 无项目授权的 Mock 接口已移除，返回 404。没有匿名可读取的业务数据接口。

创建任务示例（编号仅为格式示意）：

```json
{"title":"登记表单实现","requirement_id":"REQ-001","description":"支持记录需求来源","owner_id":null,"due_date":"2026-10-01","sprint":"S1"}
```

任务返回包含 `id, project_id, requirement_id, title, description, owner_id, owner_name, owner_active, due_date, sprint, status, version, created_by, creator_name, created_at, updated_at`。未分配时 owner_id 为 null。已移除负责人保留 ID／姓名，owner_active 为 false。日期为 ISO 日期，事件及记录时间为带时区的 UTC ISO 时间。

任务编辑提交 `title, description, owner_id, due_date, sprint, version`；不支持借编辑改绑需求或跳过状态规则。旧 version 返回 409。创建时禁止自行设置 status、id、created_by 等字段。

状态请求示例：

```json
{"status":"待验收","version":2,"reason":"","acceptance_confirmed":false}
```

状态路径为待办→进行中→待验收→已完成。进行中→待办、待验收→进行中必须填写退回原因。只有管理员可最终验收，且必须提交 `acceptance_confirmed: true`；验收事件保存验收人、实际时间及前后值。已完成不可直接编辑或回退，重开／取消属于 Sprint 2。

| 状态码 | 含义 | 示例 detail |
| --- | --- | --- |
| 401 | 无会话、过期或退出；登录凭据错误 | 请登录后继续／账号或密码错误 |
| 403 | 项目无权、只读、需要管理员、请求校验失败 | 观察者仅可读取 |
| 404 | 项目范围内对象不存在 | 需求不存在 |
| 409 | 重复成员、最后管理员、旧版本或非法流转 | 任务已被更新，请刷新后重试 |
| 422 | 缺字段、空白、非法日期／选项／负责人、缺退回原因或验收确认 | 输入不合法，请检查必填字段、日期和选项 |
| 503 | 数据库读写失败，事务回滚 | 保存或读取失败，请稍后重试 |

每个项目业务请求复用同一会话及 membership 检查，权限结果不缓存到令牌。业务变更和 append-only events 在同一事务提交，提交完成后才返回成功。并发最后管理员操作串行校验，任务更新通过 version 防止覆盖。

事件字段：project_id、entity_type、entity_id、event_type、actor_id、occurred_at、before_json、after_json、reason、operation_id。成员添加／变更／移除也记事件。S1 不提供事件修改或查询接口；S2 查询应继续复用项目授权，禁止用快照补造历史。
