# Sprint 4 API 契约

Sprint 4 延续 `/api/projects/{project_id}` 项目作用域、HttpOnly 会话 Cookie、写请求 `X-Requested-With: aimanager` 校验、snake_case 字段及统一错误结构。UML 数据每次请求都按当前项目成员关系和 `uml.read`／`uml.write` 权限授权；内置管理员与成员可读写，观察者只读，自定义角色默认没有新增权限。

## 需求故事角色

创建和编辑需求新增 `story_role` 字段，最大 200 字，可为空。需求当前版本及旧版本均保存该字段。空角色不会被系统猜测；生成用例图时以 `missing_role` 提示定位到对应 `REQ-ID`。

## UML 中心

`GET /uml` 返回当前项目的完整 UML 快照：

- `source_version`：需求、任务、成员或排期关键数据变化共用的项目来源版本。
- `use_case`：最近一次有效用例图生成版本；未生成时为 `null`。
- `use_case_stale`：最近生成版本是否落后于当前来源版本。
- `scenarios`：结构化时序场景，包含场景版本、最近有效生成版本和 `generation_stale`。

`POST /uml/use-case/generate` 请求：

```json
{"source_version": 12}
```

服务端同时读取当前项目的故事角色、需求版本和关联任务，生成 `actors`、`use_cases` 与覆盖结果。缺少角色、缺少关联任务、重复角色与用例关系、少于两个完整核心场景分别返回可定位警告。来源版本过期返回 409；成功结果以新图版本只追加保存，不修改旧版本。

## 时序场景

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/uml/scenarios` | 列出当前项目的结构化场景及最近生成版本 |
| POST | `/uml/scenarios` | 新建场景 |
| GET | `/uml/scenarios/{scenario_id}` | 读取一个场景 |
| PATCH | `/uml/scenarios/{scenario_id}` | 按场景版本更新参与者和消息 |
| POST | `/uml/scenarios/{scenario_id}/generate` | 从当前场景版本生成新时序图版本 |

场景创建或编辑请求示例：

```json
{
  "name": "需求转任务",
  "description": "产品负责人从已确认需求建立实施任务",
  "participants": ["产品负责人", "前端页面", "服务端 API", "任务服务"],
  "messages": [
    {
      "from_participant": "产品负责人",
      "to_participant": "前端页面",
      "label": "提交已确认需求",
      "branch_condition": "",
      "task_id": "T-001"
    }
  ]
}
```

更新时另传当前 `version`。参与者名称必须唯一；每条消息的发送方和接收方必须存在于参与者清单，且必须关联当前项目的真实任务。控制字符、非法参与者、无来源消息或跨项目任务返回可定位的 422，整个事务回滚，不改变场景，也不覆盖最近有效图版本。

生成请求：

```json
{"scenario_version": 2}
```

版本过期返回 409。成功结果按数组顺序生成消息次序，保留条件分支、`T-ID`、对应 `REQ-ID`、任务版本和取消标记；不读取计划日期推断消息或参与者。每次成功生成都在 `uml_generations` 增加一条不可更新、不可删除的版本记录。

## 权限和一致性

- `uml.read` 允许读取已生成图和场景；`uml.write` 允许维护场景及生成新版本。
- 生成用例图还要求 `requirement.read` 与 `task.read`；维护和生成时序图还要求 `task.read`。
- 所有需求、任务和场景查询均带当前 `project_id`；猜测其他项目的场景编号不会返回数据。
- UML 页面只通过 `frontend/src/api.js` 读取这些接口，不从 `mock.js` 回退，也不自动写入业务数据。
