# Sprint 2 API 契约

Sprint 2 延续 `/api/projects/{project_id}` 项目作用域、同源 Cookie、`X-Requested-With: aimanager` 写请求校验、snake_case 字段和统一错误结构。所有接口在请求时读取当前成员关系和权限；任务、需求、容量、事件均限定在当前项目。

## 需求版本与进展

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/requirements` | 创建优先级和非空 `acceptance_criteria` |
| PATCH | `/requirements/{req_id}` | 提交完整内容、`version`、非空 `reason`；旧版本返回 409 |
| GET | `/requirements/{req_id}/versions` | 当前版本及不可覆盖的旧版本，含操作者、实际时间和原因 |
| GET | `/requirements/{req_id}/progress` | 返回全部关联任务及取消标记，并计算有效任务数和已完成数 |

需求优先级为 `Must | Should | Could | Won't`。需求修改后，仅有效关联任务设置 `review_required=true`，产生 `source_requirement_changed` 任务事件；不自动修改任务状态、Sprint 或完成结果。

## 任务筛选 状态与完成率

`GET /tasks` 支持 `q`、`owner_id`、`status` 和 `cancelled`：

- `owner_id=unassigned` 表示未分配。
- `cancelled=active | only | all`，默认只返回有效任务。
- 关键词匹配任务号、标题、描述、需求号和负责人。

`GET /statistics/completion` 接受相同筛选，返回四状态计数、取消数、取消已完成数、有效分子／分母和一位小数完成率。待验收不计完成；取消项排除；空分母返回 `completion_rate: null`。`current_week` 采用北京时间周一 00:00 到下周一 00:00 的左闭右开区间，并返回该周 `reopened_count`。

## 依赖 阻塞 工时与容量

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/tasks/{task_id}/dependencies` | 新增同项目前置任务和原因；拒绝自身、重复、跨项目与循环 |
| DELETE | `/tasks/{task_id}/dependencies/{depends_on_id}` | 提交非空原因并解除依赖 |
| PATCH | `/tasks/{task_id}/blocker` | 保存或解除独立的人工阻塞原因，带任务版本 |
| PATCH | `/tasks/{task_id}/plan` | 保存估算／实际／剩余工时、计划起止日、锁定标记、版本和可选原因 |
| PATCH | `/members/{user_id}/capacity` | 保存周容量、可用起止日、技能标签、容量版本和可选原因 |

工时和容量不得为负；周容量上限 168 小时；计划结束不得早于开始，可用结束不得早于开始；技能标签不得重复。计划和容量修改都写入 append-only 事件并执行并发版本检查。

## 取消 重开与历史

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| PATCH | `/tasks/{task_id}/cancel` | 仅内置管理员；`version` 和非空 `reason`；状态字段不改，写入取消人和实际时间 |
| PATCH | `/tasks/{task_id}/reopen` | 仅内置管理员；仅已完成且未取消任务；重开到进行中 |
| GET | `/tasks/{task_id}/history` | 具有历史读取权限者查看只读事件及明确的历史缺口 |

取消任务不能继续编辑、流转、改绑、维护排期、阻塞或依赖，也不能恢复取消或物理删除。取消已完成任务写入独立 `cancelled_completed` 事件。重开保留原 `accepted` 事件并新增 `reopened` 事件；再次验收产生新的验收事件。

历史响应包含 `readonly: true`、`events` 和 `missing_records`。事件含操作者、实际时间、前后 JSON 和原因；接口不提供修改或删除方法，SQLite 触发器也拒绝更新和删除事件。缺少创建事件或源变更记录时返回明确说明，不按当前任务快照补造。

## 保留的候选能力

以下接口来自上一版实现，在三阶段融合版中属于未排期候选，继续保留但不计入 Sprint 2 八条 Must：

- US10：`/milestones`、`/milestones/{id}`、`/milestones/{id}/tasks`。
- US20：`PATCH /tasks/{task_id}/source`。
- US22、US23、US25：`/roles`、`/roles/permissions`、`PATCH /members/{user_id}`。

自定义角色不能获得成员／角色管理、最终验收、重开或取消权限；这些敏感操作始终由服务端保留给内置管理员。
