# Sprint 6 API 契约

所有路径均位于 `/api/projects/{project_id}`，需要有效会话、项目成员身份和 `X-Requested-With: aimanager`。Sprint 6 复用 Sprint 5 的 `ai.read`、`ai.write`、`ai.apply` 权限、统一模型配置、失败记录、草案版本和幂等应用规则。

## AI 中心

### `GET /ai`

除原有服务状态、共享数据版本和调用记录外，新增：

- `risk_thresholds`：当前负荷和阻塞阈值；尚未确认时返回版本 0 和 100%／1 工作日默认值。
- `risk_threshold_history`：最近 20 个只追加阈值版本及变更人、时间和原因。
- `quality_targets`：当前项目可承接质量任务的需求编号和标题。
- `members`：可作为建议负责人或行动负责人的有效非观察者成员。
- `actions`：风险和效率改进行动，进行中、待处理、已完成依次排列。

观察者可读取这些数据，但不能生成、应用或更新行动。

## US44 风险预警

### `POST /ai/risks`

```json
{
  "as_of_date": "2026-10-24",
  "overload_percent": 100,
  "blocked_workdays": 1,
  "threshold_reason": "终验前采用规划基线"
}
```

日期可为空，默认使用 Asia/Shanghai 当前时间。服务端先确定性计算：

- 有效未完成任务的剩余工时除以负责人周容量，结果大于 `overload_percent` 时触发超载；
- 当前人工阻塞从最近一次 `blocked` 事件起累计工作时长，结果大于 `blocked_workdays` 时触发；
- 未完成且未取消任务的截止日早于分析日时触发逾期；
- 进度预测结束日晚于截止日时触发预测延期。

负责人、截止日、周容量或阻塞开始事件缺失时进入 `missing_data`，不补造指标。风险项包含稳定 `risk_id`、影响任务、指标、阈值和证据。AI 必须逐项返回风险级别、建议、有效负责人和下一检查日期；不能增删服务端触发项。

首次调用会形成阈值版本 1。后续阈值变化必须填写 `threshold_reason`，每次变化新增版本和事件；历史不能更新或删除。模型失败不删除已确认的阈值版本。

## US45 质量分析

### `POST /ai/quality-analyses`

```json
{
  "target_requirement_id": "REQ-001",
  "owner_id": 2,
  "due_date": "2026-10-31",
  "artifacts": [
    {"artifact_type":"code","file_name":"service.py","version":"abc123","content_scope":"10-40行","content":"..."},
    {"artifact_type":"document","file_name":"README.md","version":"v2","content_scope":"运行说明","content":"..."},
    {"artifact_type":"test_report","file_name":"report.txt","version":"run-7","content_scope":"失败与覆盖","content":"..."}
  ]
}
```

`artifact_type` 只能为 `code`、`document`、`test_report`，三类均至少一项。文件名、版本、内容范围和非空内容都会保存到调用输入。目标需求必须属于当前项目；负责人可为空，否则必须是有效项目成员。

模型返回问题类别、文件、位置、标题、逐字证据、影响、建议和 `defect`／`improvement` 类型。服务端逐项校验文件属于本次输入，且 `evidence` 能在对应输入内容中定位。无法定位的结论使本次调用成为 `failed`，不会创建任务。

## US46 效率优化

### `POST /ai/efficiency-analyses`

```json
{"as_of_date":"2026-10-24"}
```

服务端从只追加任务事件和当前任务／容量数据复算：

- `average_cycle_hours`：有开始和完成事件的任务平均周期；
- `average_wait_hours`：任务创建到首次进入进行中的平均等待；
- `reopen_count`：重开事件数；
- `blocked_hours`：阻塞到解除或分析时点的工作小时；
- `load_gap_percent`：有效成员当前负荷率最大值与最小值之差。

响应保留参与计算的任务记录、成员负荷和覆盖期。少于三条含开始、完成时间的任务记录时，`data_sufficient=false`，模型必须返回空 `bottlenecks`，不能给出确定性效率结论。建议只能引用返回的指标，负责人必须是有效成员，且不得评价个人绩效。

## 审查与应用

三项能力均使用 Sprint 5 的接口：

- `PATCH /ai/runs/{run_id}`：修改 AI 建议文字，但不能修改风险／效率证据、成员候选或质量输入资料。
- `POST /ai/runs/{run_id}/reject`：保存否决和理由，不改业务数据。
- `POST /ai/runs/{run_id}/apply`：检查权限、草案版本、共享数据版本和唯一 `operation_id` 后原子应用。

应用结果：

- 风险预警：每项风险创建一条 `improvement_actions`，保留原 AI 风险和审查历史。
- 质量分析：每项已核实问题在目标需求下创建 S6 缺陷或改进任务，保存文件、位置、证据、影响和建议；需要 `task.write`。
- 效率优化：每项瓶颈创建含负责人、期限、基线指标和复核指标的行动。

任何失败、否决、权限不足、草案或共享数据版本冲突都不会产生部分任务或行动。

## 改进行动

### `PATCH /ai/actions/{action_id}`

开始行动：

```json
{"status":"进行中","version":1,"current_metric_value":null,"review_note":""}
```

复核并关闭：

```json
{"status":"已完成","version":2,"current_metric_value":8.5,"review_note":"重新采集指标并由非作者复核"}
```

关闭必须填写当前指标和复核说明，且当前指标必须小于行动创建时的 `baseline_metric_value`。不满足时返回 409；遗漏数据返回 422。已完成行动作为历史记录保留，不能重新打开。每次状态变化写入项目事件。

## 数据升级

schema 7 扩展 `ai_runs.capability` 为六项能力，迁移时重建 `ai_runs`／`ai_reviews` 并复制原数据，再做外键检查。新增：

- `risk_threshold_versions`：只追加阈值历史；
- `improvement_actions`：风险／效率行动、基线、复核和完成信息。

重复启动不会重复迁移或删除 Sprint 1—5 数据。
