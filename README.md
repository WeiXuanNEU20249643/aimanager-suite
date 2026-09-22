# 爱管理

在现有 React + Vite、FastAPI、SQLite 工程中增量实现项目规划。Sprint 1 已接入真实数据库；保留原有导航、蓝白配色、卡片、表格及右侧详情布局。设计参考位于 `design-references/`。

## Sprint 1

- US01：账号登录、刷新恢复会话、服务端退出失效。
- US02 / US06：项目成员、管理员／成员／观察者、每次请求授权、跨项目隔离、撤权即时生效、最后一名管理员保护。
- US16 / US17：独立需求、来源、唯一编号、初始版本及创建事件，编号／关键词检索和稳定详情地址。
- US03 / US04：从同项目需求创建任务；维护标题、描述、单一负责人、截止日期、S1—S6；提交及管理员验收；关键变更与事件原子提交。
- US29：任务列表和四列看板共用数据与详情，变更后重新读取。

## Sprint 2

- Must US18 / US19：需求编辑形成不可覆盖版本，维护 MoSCoW 优先级和可测验收条件，关联任务只标记待复核。
- Must US09 / US33：同项目任务依赖、循环检测、人工阻塞；任务估算／实际／剩余工时、计划日期与锁定；成员周容量、可用时段和技能。
- Must US11：任务详情查询只读关键变更历史，展示操作者、实际时间、前后值和原因；缺失历史明确提示，不按快照补造。
- Must US27 / US28：内置管理员带原因取消任务、重开已完成任务；取消项保留最后状态并退出有效分母，重开保留原验收事件。
- Must US05：四状态实时概览，取消项单列，点击进入相同项目和筛选口径的任务明细。
- Should US07 / US21 / US30：组合筛选、按需求查看任务进展和可复算的一位小数整体完成率。

项目概览、需求管理、任务列表／看板和成员容量已经接入 Sprint 2 真实接口。上一版已完成的 US10 里程碑、US20 任务源需求改绑，以及 US22／US23／US25 自定义角色能力，在融合版中属于候选未排期功能，继续保留作为可复用增量，不计入本轮八条 Must。

Sprint 2 结束时，甘特、成员任务图、UML、AI 和设置页面仍为原始设计预览；Sprint 3 在此基础上只接入甘特和成员任务图，没有提前实现后续迭代。

## Sprint 3

- US34：甘特图从统一排期接口读取真实任务、计划日期、负责人、工时与依赖；任务条进入同一任务详情，未排期和已取消任务明确分开。
- US35：成员任务图按有效成员、已移除历史负责人和未分配任务分组，以剩余工时和计划期容量计算负荷，不把任务数量当作绩效。
- US36：需求详情提供排期影响清单；内置管理员确认后，服务端按依赖、成员可用时段和容量原子重排待办且未锁定任务，保留已完成、进行中、待验收和锁定任务的承诺日期，并保存排期版本、旧新日期、冲突及操作者。
- US37：看板、甘特和成员任务图共享任务 ID、状态、负责人、取消标记和任务版本；成员任务图每 5 秒静默重读，网络失败不以旧数据覆盖新版本。

Sprint 3 结束时，甘特、成员任务图和需求排期影响均已接入真实 FastAPI + SQLite 数据；UML、AI 和设置页面仍保留原始设计预览，等待后续迭代接入。

## Sprint 4

- US38：需求新增结构化故事角色；UML 用例图从当前项目的角色、需求版本和关联任务生成，缺少角色、缺少任务及重复关系均返回可定位提示；重新生成保留旧版结果。
- US39：业务场景保存显式参与者、消息顺序、条件分支和来源任务；时序图只按这些步骤生成，不从甘特日期推断调用；非法参与者、无来源消息及控制字符错误不会覆盖上一个有效版本。

UML 中心已接入真实 FastAPI + SQLite 数据，并与需求、任务共用稳定的 `REQ-ID`、`T-ID`、项目权限和版本。按规划基准，Sprint 4 的退出条件是 US38、US39 两条 Must 及 Sprint 3 回归通过；US40、US12、US13 为 Should，本轮未提前实现并保留到后续容量评审。在 Sprint 4 交付点，AI 和设置页面仍为禁用的设计预览。

## Sprint 5

- US47：统一服务端 AI 调用、结构化输出校验和人工审查；保存输入版本、模型、时间、原始／修改输出及审查理由。草案可修改、采纳或否决，确认应用使用操作标识幂等执行，权限和数据版本在服务端再次核验。
- US41：提交有来源的 PRD 文本后真实调用模型，生成角色、故事、验收条件、任务、依赖、技能及工时草案；无法在原文定位的建议单列，只有人工确认后才创建独立需求与关联任务。
- US42：从已完成任务读取估算与实际工时；有效样本不少于三条时按实际／估算比中位数校准剩余工时，再结合依赖和成员容量计算预计日期。样本不足时明确显示未校准基准计划，AI 只解释服务端可复算结果。
- US43：服务端先按优先级、依赖、所需技能、成员容量和可用期生成确定性排期，再由 AI 解释分配理由和取舍；循环、缺少技能／容量、未排前置任务等冲突可定位，锁定、进行中、待验收和已完成任务不移动。

AI 分析页已替换原设计预览，接入真实调用记录、PRD 拆解编辑、预测证据、排期差异以及采纳／否决流程。失败、否决和版本冲突均不修改需求、任务或排期；确认后的排期使用同一任务库，因此甘特和成员任务图会读取到更新结果。

## Sprint 6

- US44：按负荷超过阈值、阻塞超过阈值、任务逾期和预测晚于截止日四类确定性规则生成风险证据；阈值变更只追加留痕，AI 为每项风险给出级别、负责人、检查时间和应对建议。人工采纳后形成独立行动，保留原风险记录；只有复核指标优于创建基线并填写说明后才能关闭。
- US45：有权成员选定代码片段、需求或说明文档、测试报告，三类资料均保存文件名、版本和内容范围。AI 问题必须引用输入中的逐字证据和位置，人工确认后才转为关联现有需求的 S6 缺陷或改进任务；静态分析不冒充实际运行测试。
- US46：服务端从任务事件复算周期、等待、返工、阻塞工作时长和成员负荷差异，展示参与记录及覆盖期；不足三条完整任务记录时不生成确定性瓶颈。AI 建议只面向流程、任务切分和工作分配，不评价个人绩效；采纳后形成含负责人、期限和复核指标的行动。

AI 分析中心现在统一展示六项 AI 能力及只追加审查历史。风险与效率行动在同一页面持续跟踪，质量问题写回统一任务库，因此看板、甘特和成员任务图读取同一份确认结果。

## 首次运行 Windows PowerShell

要求 Python 3.13 或 3.14、Node.js 24。两个终端分别运行后端和前端。

后端初始化（仅首次需要创建账号和项目；密码由终端隐藏输入，无默认密码）：

```powershell
cd E:\A_DevManage\aimanager-suite\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.manage migrate
.\.venv\Scripts\python.exe -m app.manage create-user admin --name '项目管理员'
.\.venv\Scripts\python.exe -m app.manage create-project '爱管理项目' --admin admin
```

需要其他成员时，使用 `create-user` 开通账号，再由管理员在页面“成员与权限”中添加已有账号和选择角色。观察者也是独立账号。为验证项目隔离，可通过 `create-project` 创建第二个项目并指定其管理员。

启动后端：

```powershell
cd E:\A_DevManage\aimanager-suite\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Sprint 5 和 Sprint 6 的六项 AI 能力使用服务端环境变量，不把凭据下发前端。接口兼容 OpenAI Chat Completions 风格的结构化 JSON 响应：

```powershell
$env:AIMANAGER_AI_ENDPOINT='https://your-provider.example/v1/chat/completions'
$env:AIMANAGER_AI_MODEL='your-structured-output-model'
$env:AIMANAGER_AI_API_KEY='your-server-side-key'
$env:AIMANAGER_AI_TIMEOUT_SECONDS='30'
```

也可设置 `AIMANAGER_AI_BASE_URL`，服务端会在其后追加 `/chat/completions`。`AIMANAGER_AI_ENDPOINT` 优先。未配置时页面明确显示不可调用；超时、429、连接失败和结构错误会保存失败记录，不会写入业务数据。

启动前端：

```powershell
cd E:\A_DevManage\aimanager-suite\frontend
npm ci
npm run dev
```

访问 http://127.0.0.1:5173 。开发代理把同源 `/api` 转发到 `127.0.0.1:8000`。地址统一使用 `127.0.0.1`，不要在操作中切换主机名。API 文档：http://127.0.0.1:8000/docs 。写请求需要 `X-Requested-With: aimanager`，浏览器适配层自动设置。

## 数据库与升级

### 本地业务数据与 GitHub

代码和本地业务数据分开保存：数据库及备份放在 `backend/data/`，个人导入脚本、业务映射与账号交接文件放在 `.local/`。两处均已被 Git 忽略；`.env`、环境私密配置和 SQLite 数据文件也不提交。示例配置可使用不含凭据的 `.env.example`。不要把真实账号、密码、业务记录或数据库复制到源码、测试夹具、设计预览和公开文档中，也不要用 `git add -f` 强制添加。

提交前用 `git status --short` 和 `git diff --cached --name-only` 检查暂存内容；用 `git check-ignore -v <文件路径>` 核实本地文件被忽略。忽略规则不等于备份，也不能阻止强制添加或已追踪文件泄漏。正常 GitHub 提交仅同步代码，不同步本地账号和项目数据；换电脑时须通过私密渠道另行迁移数据库。后续开发继续使用增量迁移，不重新初始化或清空现有库。

默认数据库为 `backend/data/aimanager.sqlite3`，与工作目录无关。可在启动前设置 `$env:AIMANAGER_DB='绝对路径'`。程序启动自动执行增量迁移；也可单独执行 `python -m app.manage migrate`。Sprint 2 通过 schema 2 保留需求版本、角色权限、依赖和里程碑结构，并以 schema 3 增量加入任务工时／排期和成员容量结构；Sprint 3 的 schema 4 新增项目排期版本和需求重排记录；Sprint 4 的 schema 5 增加故事角色、结构化时序场景和只追加 UML 生成版本；Sprint 5 的 schema 6 增加任务技能要求、AI 调用记录和只追加审查记录；Sprint 6 的 schema 7 扩展六项 AI 类型，增加只追加风险阈值版本和可复核改进行动。重复迁移保留数据；遇到高于程序支持的版本直接拒绝启动。没有自动导入原 Mock 数据，不会把规划故事编号冒充产品运行数据。

升级前停止后端并备份数据库文件。后续版本必须增加迁移分支和迁移回归用例，不能删除或覆盖数据库。原工程只有内存数组，没有需要搬迁的既有 SQLite 业务数据。需求号 `REQ-001…` 和任务号 `T-001…` 由数据库自增主键生成，全库唯一且稳定，所有读取仍按项目授权。

密码采用 PBKDF2-SHA256 加盐散列；浏览器仅持有 HttpOnly / SameSite=Strict 会话 Cookie，服务端保存会话令牌的散列，12 小时有效，退出删除服务端会话。HTTP 仅用于本地开发；HTTPS 部署应设置 `AIMANAGER_SECURE_COOKIE=1` 并把前端与 API 放到同一站点。

## 路由与代码

- `#overview?project=1`：实时状态、完成率、里程碑及成员容量概览。
- `#requirements?project=1`、`#requirements/REQ-001?project=1`：需求列表／详情。
- `#kanban?project=1`、`#kanban/T-001?project=1`：四列看板／任务详情。
- `#tasks?project=1`、`#tasks/T-001?project=1`：任务列表／同一详情。
- `#gantt?project=1`：真实任务甘特图、未排期清单和共享排期版本。
- `#members?project=1`：真实成员任务分组、容量负荷和 5 秒同步。
- `#uml?project=1`：真实用例图、结构化时序场景及可追溯生成版本。
- `#ai?project=1`：六项真实 AI 调用、风险／质量／效率证据、人工审查及改进行动。
- `#permissions?project=1`：项目成员及角色。

详情支持刷新、浏览器前进后退；未登录先登录再回到目标地址。顶部选择项目会清除上个项目的对象编号。无权限、空结果、加载失败分别提示；失败不会回退为 Mock。

`frontend/src/components.jsx` 与 `styles.css` 继续提供统一视觉组件。`src/api.js` 是唯一网络适配层；`src/sprint1/` 保留共用加载逻辑并增量扩展需求、任务和权限页，`src/sprint2/Overview.jsx` 提供真实概览，`src/sprint3/` 提供甘特、成员任务图和静默同步，`src/sprint4/` 提供真实 UML 中心，`src/sprint5/` 提供统一 AI 调用和审查中心，`src/sprint6/` 提供风险、质量、效率与行动闭环样式；`pages.jsx`、`mock.js` 仅供尚未接入页面的设计预览。后端 `db.py` 管理数据库与迁移，`schemas.py` 约束输入，`planning.py` 负责排期影响、容量计算和重排规则，`uml.py` 负责结构化 UML 映射和版本读取，`ai.py` 负责六项模型调用、确定性证据和输出校验，`main.py` 提供统一项目授权与 API。SQLite 使用 Python 标准库事务；没有另建项目或服务。

## 测试

```powershell
cd E:\A_DevManage\aimanager-suite\backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
npm run test:e2e:sprint2
npm run test:e2e:sprint3
npm run test:e2e:sprint4
npm run test:e2e:sprint5
npm run test:e2e:sprint6
```

Windows 已安装 Edge 时，可设置 `$env:PLAYWRIGHT_CHANNEL='msedge'` 使用 Edge 无头测试，无需下载 Chromium。浏览器测试自动启动独立端口 18000／15173，使用临时 SQLite、随机测试密码及明确标注的测试项目，结束时停止服务并清理临时目录，不改正式库。截图输出在忽略目录 `artifacts/`。可用 `AIMANAGER_TEST_PYTHON` 指定测试 Python 路径。

Sprint 1 的历史验证和契约见 `docs/sprint1-validation.md`、`docs/api-sprint1.md`；Sprint 2 见 `docs/sprint2-validation.md`、`docs/api-sprint2.md` 和 `docs/sprint2-handover.md`；Sprint 3 见 `docs/sprint3-validation.md`、`docs/api-sprint3.md` 和 `docs/sprint3-handover.md`；Sprint 4 见 `docs/sprint4-validation.md`、`docs/api-sprint4.md` 和 `docs/sprint4-handover.md`；Sprint 5 见 `docs/sprint5-validation.md`、`docs/api-sprint5.md` 和 `docs/sprint5-handover.md`；Sprint 6 见 `docs/sprint6-validation.md`、`docs/api-sprint6.md` 和 `docs/sprint6-handover.md`。自动化结果为本地验证，不替代非作者人工复验、产品接受或远端 CI。
