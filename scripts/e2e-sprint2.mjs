import {createRequire} from 'node:module';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve, join, sep, basename} from 'node:path';
import {randomBytes} from 'node:crypto';
import assert from 'node:assert/strict';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = resolve(import.meta.dirname, '..');
const temp = mkdtempSync(join(tmpdir(), 'aimanager-s2-e2e-'));
const output = join(root, 'artifacts'); mkdirSync(output, {recursive: true});
const python = process.env.AIMANAGER_TEST_PYTHON || join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const password = randomBytes(24).toString('base64url');
const env = {...process.env, AIMANAGER_DB: join(temp, 'test.sqlite3'), PYTHONIOENCODING: 'utf-8', PYTHONPATH: join(root, 'backend')};
const seed = spawnSync(python, ['tests/seed_e2e.py'], {cwd: join(root, 'backend'), env, input: JSON.stringify({password}), encoding: 'utf8', windowsHide: true});
if (seed.status !== 0) throw new Error(seed.stderr);
const backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '18001', '--no-access-log'], {cwd: join(root, 'backend'), env, stdio: 'pipe', windowsHide: true});
const frontend = spawn(process.execPath, [join(root, 'frontend/node_modules/vite/bin/vite.js'), '--port', '15174'], {cwd: join(root, 'frontend'), env: {...env, AIMANAGER_API_TARGET: 'http://127.0.0.1:18001'}, stdio: 'pipe', windowsHide: true});
let logs = ''; for (const processHandle of [backend, frontend]) { processHandle.stdout.on('data', chunk => logs += chunk); processHandle.stderr.on('data', chunk => logs += chunk); }
let browser;
async function untilServer(url) { for (let index = 0; index < 100; index++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise(resolveWait => setTimeout(resolveWait, 150)); } throw new Error('Server startup failed: ' + logs); }
async function login(page, username) {
  await page.goto('http://127.0.0.1:15174');
  await page.getByLabel('账号 / 邮箱').fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '登 录', exact: true}).click();
  await page.waitForURL('**/#overview?project=1');
}

try {
  await untilServer('http://127.0.0.1:18001/api/health');
  await untilServer('http://127.0.0.1:15174');
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const adminContext = await browser.newContext({viewport: {width: 1480, height: 1040}});
  const admin = await adminContext.newPage();
  const errors = []; admin.on('pageerror', error => errors.push(error.message));
  await login(admin, 'qa_admin');

  await admin.getByRole('button', {name: '新建里程碑', exact: true}).click();
  await admin.getByLabel('里程碑名称').fill('Sprint 2 浏览器验收');
  await admin.getByLabel('目标日期').fill('2026-10-10');
  await admin.getByRole('button', {name: '保存里程碑'}).click();
  await admin.getByText('Sprint 2 浏览器验收', {exact: true}).waitFor();

  await admin.getByRole('button', {name: '需求管理', exact: true}).click();
  await admin.getByRole('button', {name: '新建需求', exact: true}).click();
  await admin.getByLabel('标题', {exact: true}).fill('Sprint 2 浏览器需求');
  await admin.getByLabel('需求描述', {exact: true}).fill('验证版本、进展和任务依赖的真实数据链路。');
  await admin.getByLabel('来源', {exact: true}).fill('Sprint 2 自动化测试');
  await admin.getByLabel('优先级').selectOption('Must');
  await admin.getByLabel('验收条件', {exact: true}).fill('组合筛选与完成率使用相同任务口径。');
  await admin.getByRole('button', {name: '保存需求'}).click();
  await admin.getByRole('heading', {name: 'Sprint 2 浏览器需求', exact: true}).waitFor();
  const requirementUrl = admin.url();
  await admin.getByRole('button', {name: '编辑需求'}).click();
  await admin.getByLabel('优先级').selectOption('Should');
  await admin.getByLabel('验收条件', {exact: true}).fill('列表和看板筛选一致，统计可回查。');
  await admin.getByLabel('变更原因').fill('评审后补充可测口径');
  await admin.getByRole('button', {name: '保存新版本'}).click();
  await admin.getByText('版本 2', {exact: true}).waitFor();
  await admin.getByText('评审后补充可测口径', {exact: true}).first().waitFor();

  await admin.getByRole('button', {name: '从此需求创建任务'}).click();
  await admin.getByLabel('任务标题').fill('前置接口任务');
  await admin.getByLabel('里程碑').selectOption({index: 1});
  await admin.getByRole('button', {name: '创建任务'}).click();
  await admin.getByRole('heading', {name: '前置接口任务', exact: true}).waitFor();
  const firstId = (await admin.locator('.drawer-top>b').innerText()).trim();
  await admin.getByLabel('估算工时').fill('8');
  await admin.getByLabel('实际工时').fill('2');
  await admin.getByLabel('剩余工时').fill('6');
  await admin.getByLabel('计划开始').fill('2026-09-20');
  await admin.getByLabel('计划结束').fill('2026-09-24');
  await admin.getByLabel('锁定当前排期').check();
  await admin.locator('input[name=reason]').fill('浏览器排期确认');
  await admin.getByRole('button', {name: '保存工时与排期'}).click();
  await admin.getByText('8h / 2h / 6h', {exact: true}).waitFor();

  await admin.getByRole('button', {name: '新建任务', exact: true}).click();
  await admin.getByLabel('源需求').selectOption({index: 1});
  await admin.getByLabel('任务标题').fill('后续联调任务');
  await admin.getByLabel('里程碑').selectOption({index: 1});
  await admin.getByRole('button', {name: '创建任务'}).click();
  await admin.getByRole('heading', {name: '后续联调任务', exact: true}).waitFor();
  const secondId = (await admin.locator('.drawer-top>b').innerText()).trim();
  await admin.getByLabel('依赖变更原因').fill('必须先完成前置接口');
  await admin.getByLabel('前置任务').selectOption(firstId);
  await admin.getByRole('button', {name: '添加依赖'}).click();
  await admin.getByText('必须先完成前置接口', {exact: false}).first().waitFor();
  await admin.getByLabel('人工阻塞原因').fill('等待联调环境');
  await admin.getByRole('button', {name: '标记人工阻塞'}).click();
  await admin.getByText('人工阻塞', {exact: true}).first().waitFor();

  await admin.getByLabel('任务关键词').fill('后续');
  await admin.getByLabel('负责人筛选').selectOption('unassigned');
  await admin.getByLabel('状态筛选', {exact: true}).selectOption('待办');
  await admin.getByText(/当前 1 项/).waitFor();
  assert.equal(await admin.getByText('前置接口任务', {exact: true}).count(), 0);
  await admin.screenshot({path: join(output, 'sprint2-task-filters.png'), fullPage: true});

  await admin.getByRole('button', {name: '项目概览', exact: true}).click();
  await admin.getByText('Sprint 2 浏览器验收', {exact: true}).waitFor();
  const capacityRow = admin.getByRole('row').filter({hasText: '测试成员'});
  await capacityRow.getByRole('button', {name: '维护容量'}).click();
  await admin.getByLabel('每周容量').fill('20');
  await admin.getByLabel('可用开始日期').fill('2026-09-20');
  await admin.getByLabel('可用结束日期').fill('2026-10-24');
  await admin.getByLabel('技能标签').fill('React, FastAPI');
  await admin.getByRole('dialog').locator('textarea[name=reason]').fill('浏览器确认成员容量');
  await admin.getByRole('button', {name: '保存容量'}).click();
  await capacityRow.getByText('20 小时', {exact: true}).waitFor();
  await admin.screenshot({path: join(output, 'sprint2-overview.png'), fullPage: true});

  await admin.goto(`http://127.0.0.1:15174/#kanban/${firstId}?project=1`);
  await admin.getByRole('heading', {name: '前置接口任务', exact: true}).waitFor();
  await admin.getByRole('button', {name: '开始任务'}).click();
  await admin.getByRole('button', {name: '提交验收'}).click();
  await admin.getByLabel('我已核对关联需求，确认验收条件通过').check();
  await admin.getByRole('button', {name: '验收完成'}).click();
  await admin.getByText('任务已完成。', {exact: true}).waitFor();
  await admin.locator('.admin-task-actions textarea').fill('验收后发现需要返工');
  await admin.getByRole('button', {name: '重开为进行中'}).click();
  await admin.getByText('重开任务', {exact: true}).waitFor();

  await admin.goto(`http://127.0.0.1:15174/#kanban/${secondId}?project=1`);
  await admin.getByRole('heading', {name: '后续联调任务', exact: true}).waitFor();
  await admin.locator('.admin-task-actions textarea').fill('范围调整后取消联调');
  await admin.getByRole('button', {name: '取消任务'}).click();
  await admin.getByText('取消原因：范围调整后取消联调', {exact: true}).waitFor();
  await admin.getByLabel('取消状态筛选', {exact: true}).selectOption('only');
  await admin.getByText(/当前 1 项/).waitFor();
  await admin.screenshot({path: join(output, 'sprint2-cancelled-history.png'), fullPage: true});

  await admin.getByRole('button', {name: '成员与权限', exact: true}).click();
  await admin.getByRole('button', {name: '新建自定义角色', exact: true}).click();
  await admin.getByLabel('角色名称').fill('浏览器只读');
  await admin.getByLabel('角色描述').fill('只读查看需求和任务');
  await admin.getByRole('checkbox', {name: '查看需求', exact: true}).check();
  await admin.getByRole('checkbox', {name: '查看任务', exact: true}).check();
  await admin.getByRole('button', {name: '保存角色'}).click();
  await admin.getByText('浏览器只读', {exact: true}).waitFor();
  const memberRow = admin.getByRole('row').filter({hasText: 'qa_member'});
  await memberRow.getByRole('button', {name: '分配角色'}).click();
  await admin.getByLabel('项目角色').selectOption({label: '浏览器只读（自定义）'});
  await admin.getByRole('button', {name: '保存成员'}).click();
  await memberRow.getByText('浏览器只读', {exact: true}).waitFor();
  await admin.screenshot({path: join(output, 'sprint2-permissions.png'), fullPage: true});

  const memberContext = await browser.newContext({viewport: {width: 1280, height: 900}});
  const member = await memberContext.newPage(); member.on('pageerror', error => errors.push(error.message));
  await login(member, 'qa_member');
  await member.getByText('当前角色没有查看项目统计的权限。').waitFor();
  await member.getByRole('button', {name: '需求管理', exact: true}).click();
  await member.getByText('Sprint 2 浏览器需求', {exact: true}).waitFor();
  assert.equal(await member.getByRole('button', {name: '新建需求'}).count(), 0);
  await member.getByRole('button', {name: '任务看板', exact: true}).click();
  await member.getByLabel('取消状态筛选', {exact: true}).selectOption('only');
  await member.getByText('后续联调任务', {exact: true}).waitFor();
  assert.equal(await member.getByRole('button', {name: '新建任务'}).count(), 0);
  assert.deepEqual(errors, []);
  assert.match(requirementUrl, /#requirements\/REQ-\d+\?project=1/);
  await memberContext.close(); await adminContext.close();
  console.log('PASS: Sprint 2 requirements, plan data, capacity, history, cancel/reopen, filters, dependencies, statistics and retained custom-role UI.');
} catch (error) {
  if (browser) {
    let index = 0;
    for (const context of browser.contexts()) for (const page of context.pages()) {
      if (await page.locator('input[type=password]').count() === 0) {
        await page.screenshot({path: join(output, `sprint2-failure-${index++}.png`), fullPage: true});
        console.error('Failure page:', page.url(), (await page.locator('body').innerText()).slice(-4000));
      }
    }
  }
  throw error;
} finally {
  if (browser) await browser.close();
  await Promise.all([backend, frontend].map(processHandle => new Promise(resolveExit => { if (processHandle.exitCode !== null) return resolveExit(); processHandle.once('exit', resolveExit); processHandle.kill(); })));
  const target = resolve(temp);
  if (!target.startsWith(resolve(tmpdir()) + sep) || !basename(target).startsWith('aimanager-s2-e2e-')) throw new Error('Unsafe cleanup target');
  rmSync(target, {recursive: true, force: true});
}
