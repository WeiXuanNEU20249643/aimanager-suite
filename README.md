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

甘特、成员任务图、UML、AI 和设置页面保留原始设计预览，明确标注示例数据并禁用交互。后续按 Sprint 3—6 逐步接入；预览不代表功能已交付。

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

启动前端：

```powershell
cd E:\A_DevManage\aimanager-suite\frontend
npm ci
npm run dev
```

访问 http://127.0.0.1:5173 。开发代理把同源 `/api` 转发到 `127.0.0.1:8000`。地址统一使用 `127.0.0.1`，不要在操作中切换主机名。API 文档：http://127.0.0.1:8000/docs 。写请求需要 `X-Requested-With: aimanager`，浏览器适配层自动设置。

## 数据库与升级

默认数据库为 `backend/data/aimanager.sqlite3`，与工作目录无关。可在启动前设置 `$env:AIMANAGER_DB='绝对路径'`。程序启动自动执行增量迁移；也可单独执行 `python -m app.manage migrate`。Sprint 2 通过 schema 2 保留需求版本、角色权限、依赖和里程碑结构，并以 schema 3 增量加入任务工时／排期和成员容量结构。重复迁移保留数据；遇到高于程序支持的版本直接拒绝启动。没有自动导入原 Mock 数据，不会把规划故事编号冒充产品运行数据。

升级前停止后端并备份数据库文件。后续版本必须增加迁移分支和迁移回归用例，不能删除或覆盖数据库。原工程只有内存数组，没有需要搬迁的既有 SQLite 业务数据。需求号 `REQ-001…` 和任务号 `T-001…` 由数据库自增主键生成，全库唯一且稳定，所有读取仍按项目授权。

密码采用 PBKDF2-SHA256 加盐散列；浏览器仅持有 HttpOnly / SameSite=Strict 会话 Cookie，服务端保存会话令牌的散列，12 小时有效，退出删除服务端会话。HTTP 仅用于本地开发；HTTPS 部署应设置 `AIMANAGER_SECURE_COOKIE=1` 并把前端与 API 放到同一站点。

## 路由与代码

- `#overview?project=1`：实时状态、完成率、里程碑及成员容量概览。
- `#requirements?project=1`、`#requirements/REQ-001?project=1`：需求列表／详情。
- `#kanban?project=1`、`#kanban/T-001?project=1`：四列看板／任务详情。
- `#tasks?project=1`、`#tasks/T-001?project=1`：任务列表／同一详情。
- `#permissions?project=1`：项目成员及角色。

详情支持刷新、浏览器前进后退；未登录先登录再回到目标地址。顶部选择项目会清除上个项目的对象编号。无权限、空结果、加载失败分别提示；失败不会回退为 Mock。

`frontend/src/components.jsx` 与 `styles.css` 继续提供统一视觉组件。`src/api.js` 是唯一网络适配层；`src/sprint1/` 保留共用加载逻辑并增量扩展需求、任务和权限页，`src/sprint2/Overview.jsx` 提供真实概览；`pages.jsx`、`mock.js` 仅供尚未接入页面的设计预览。后端 `db.py` 管理数据库与迁移，`schemas.py` 约束输入，`security.py` 管理散列，`main.py` 提供统一项目授权与 API。SQLite 使用 Python 标准库事务；没有另建项目或服务。

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
```

Windows 已安装 Edge 时，可设置 `$env:PLAYWRIGHT_CHANNEL='msedge'` 使用 Edge 无头测试，无需下载 Chromium。浏览器测试自动启动独立端口 18000／15173，使用临时 SQLite、随机测试密码及明确标注的测试项目，结束时停止服务并清理临时目录，不改正式库。截图输出在忽略目录 `artifacts/`。可用 `AIMANAGER_TEST_PYTHON` 指定测试 Python 路径。

Sprint 1 的历史验证和契约见 `docs/sprint1-validation.md`、`docs/api-sprint1.md`；Sprint 2 见 `docs/sprint2-validation.md`、`docs/api-sprint2.md` 和 `docs/sprint2-handover.md`。当前目录没有 Git 元数据，尚未执行远端 CI，也不把自动化测试当成人工独立验收签认。
