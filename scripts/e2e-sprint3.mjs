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
const temp = mkdtempSync(join(tmpdir(), 'aimanager-s3-e2e-'));
const output = join(root, 'artifacts'); mkdirSync(output, {recursive: true});
const python = process.env.AIMANAGER_TEST_PYTHON || join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const password = randomBytes(24).toString('base64url');
const env = {...process.env, AIMANAGER_DB: join(temp, 'test.sqlite3'), PYTHONIOENCODING: 'utf-8', PYTHONPATH: join(root, 'backend')};
const seed = spawnSync(python, ['tests/seed_e2e.py'], {cwd: join(root, 'backend'), env, input: JSON.stringify({password}), encoding: 'utf8', windowsHide: true});
if (seed.status !== 0) throw new Error(seed.stderr);
const backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '18002', '--no-access-log'], {cwd: join(root, 'backend'), env, stdio: 'pipe', windowsHide: true});
const frontend = spawn(process.execPath, [join(root, 'frontend/node_modules/vite/bin/vite.js'), '--port', '15175'], {cwd: join(root, 'frontend'), env: {...env, AIMANAGER_API_TARGET: 'http://127.0.0.1:18002'}, stdio: 'pipe', windowsHide: true});
let logs = ''; for (const processHandle of [backend, frontend]) { processHandle.stdout.on('data', chunk => logs += chunk); processHandle.stderr.on('data', chunk => logs += chunk); }
let browser;
async function untilServer(url) { for (let index = 0; index < 100; index++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise(resolveWait => setTimeout(resolveWait, 150)); } throw new Error('Server startup failed: ' + logs); }
async function login(page, username) {
  await page.goto('http://127.0.0.1:15175');
  await page.getByLabel('账号 / 邮箱').fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '登 录', exact: true}).click();
  await page.waitForURL('**/#overview?project=1');
}
async function api(page, path, method = 'GET', body) {
  return page.evaluate(async ({path, method, body}) => {
    const response = await fetch('/api' + path, {method, credentials: 'same-origin', headers: {
      'Content-Type': 'application/json', 'X-Requested-With': 'aimanager',
    }, body: body === undefined ? undefined : JSON.stringify(body)});
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(data)}`);
    return data;
  }, {path, method, body});
}

try {
  await untilServer('http://127.0.0.1:18002/api/health');
  await untilServer('http://127.0.0.1:15175');
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const adminContext = await browser.newContext({viewport: {width: 1480, height: 1040}});
  const admin = await adminContext.newPage();
  const errors = []; admin.on('pageerror', error => errors.push(error.message));
  await login(admin, 'qa_admin');

  await api(admin, '/projects/1/members/2/capacity', 'PATCH', {weekly_capacity_hours: 20,
    available_from: '2026-09-13', available_to: '2026-10-24', skill_tags: ['React', 'FastAPI'],
    version: 0, reason: 'Sprint 3 浏览器容量'});
  let requirement = await api(admin, '/projects/1/requirements', 'POST', {title: 'Sprint 3 三视图联动',
    description: '验证甘特、成员任务图和看板共享任务数据。', source: 'Sprint 3 浏览器测试',
    priority: 'Must', acceptance_criteria: '需求变更后排期更新，状态变更在五秒内同步。'});
  let locked = await api(admin, '/projects/1/tasks', 'POST', {title: '已锁定接口', requirement_id: requirement.id,
    owner_id: 2, due_date: '2026-10-01', sprint: 'S3'});
  locked = await api(admin, `/projects/1/tasks/${locked.id}/plan`, 'PATCH', {estimated_hours: 8, actual_hours: 0,
    remaining_hours: 8, planned_start: '2026-09-28', planned_end: '2026-09-30', plan_locked: true,
    version: locked.version, reason: '承诺日期已锁定'});
  let movable = await api(admin, '/projects/1/tasks', 'POST', {title: '可重排页面', requirement_id: requirement.id,
    owner_id: 2, due_date: '2026-10-10', sprint: 'S3'});
  movable = await api(admin, `/projects/1/tasks/${movable.id}/plan`, 'PATCH', {estimated_hours: 12, actual_hours: 0,
    remaining_hours: 12, planned_start: '2026-10-01', planned_end: '2026-10-02', plan_locked: false,
    version: movable.version, reason: '初始页面排期'});
  await api(admin, `/projects/1/tasks/${movable.id}/dependencies`, 'POST', {depends_on_id: locked.id, reason: '页面依赖接口'});
  requirement = await api(admin, `/projects/1/requirements/${requirement.id}`, 'PATCH', {title: requirement.title + ' 二版',
    description: '确认工作量与依赖变化后重新排期。', source: requirement.source, priority: 'Should',
    acceptance_criteria: requirement.acceptance_criteria, version: requirement.version, reason: 'Sprint 3 确认变更'});

  await admin.goto(`http://127.0.0.1:15175/#requirements/${requirement.id}?project=1`);
  await admin.getByText(/项可自动重排/).waitFor();
  await admin.getByRole('button', {name: '确认并重新排期', exact: true}).click();
  const dialog = admin.getByRole('dialog');
  await dialog.getByLabel('确认原因').fill('浏览器确认需求工作量和依赖变化');
  await dialog.getByRole('button', {name: '确认并重新排期', exact: true}).click();
  await admin.getByText('排期已按依赖和成员容量更新', {exact: true}).waitFor();
  await admin.getByText('已应用', {exact: true}).waitFor();

  await admin.getByRole('button', {name: '甘特图', exact: true}).click();
  await admin.locator('.s3-gantt-bar').filter({hasText: '已锁定接口'}).waitFor();
  await admin.locator('.s3-gantt-bar').filter({hasText: '可重排页面'}).waitFor();
  await admin.getByText(`前置：${locked.id}`, {exact: true}).waitFor();
  await admin.screenshot({path: join(output, 'sprint3-gantt.png'), fullPage: true});

  await admin.getByRole('button', {name: '成员任务图', exact: true}).click();
  const memberColumn = admin.locator('.s3-member-column').filter({hasText: '测试成员'});
  await memberColumn.getByText('已锁定接口', {exact: true}).waitFor();
  await memberColumn.getByText('可重排页面', {exact: true}).waitFor();
  await admin.screenshot({path: join(output, 'sprint3-members.png'), fullPage: true});

  const updated = await api(admin, `/projects/1/tasks/${movable.id}`);
  await api(admin, `/projects/1/tasks/${movable.id}/status`, 'PATCH', {status: '进行中', version: updated.version});
  const movableCard = memberColumn.locator('a').filter({hasText: '可重排页面'});
  await movableCard.getByText('进行中', {exact: true}).waitFor({timeout: 8000});
  assert.match(await movableCard.innerText(), new RegExp(`v${updated.version + 1}`));

  const observerContext = await browser.newContext({viewport: {width: 1280, height: 900}});
  const observer = await observerContext.newPage(); observer.on('pageerror', error => errors.push(error.message));
  await login(observer, 'qa_observer');
  await observer.goto(`http://127.0.0.1:15175/#requirements/${requirement.id}?project=1`);
  await observer.getByText('当前为只读影响清单', {exact: false}).waitFor();
  assert.equal(await observer.getByRole('button', {name: '确认并重新排期', exact: true}).count(), 0);
  await observer.getByRole('button', {name: '甘特图', exact: true}).click();
  await observer.locator('.s3-gantt-bar').filter({hasText: '可重排页面'}).waitFor();
  assert.deepEqual(errors, []);
  await observerContext.close(); await adminContext.close();
  console.log('PASS: Sprint 3 shared planning, requirement replan, real Gantt, member workload and five-second board synchronization.');
} catch (error) {
  if (browser) {
    let index = 0;
    for (const context of browser.contexts()) for (const page of context.pages()) {
      if (await page.locator('input[type=password]').count() === 0) {
        await page.screenshot({path: join(output, `sprint3-failure-${index++}.png`), fullPage: true});
        console.error('Failure page:', page.url(), (await page.locator('body').innerText()).slice(-5000));
      }
    }
  }
  throw error;
} finally {
  if (browser) await browser.close();
  await Promise.all([backend, frontend].map(processHandle => new Promise(resolveExit => { if (processHandle.exitCode !== null) return resolveExit(); processHandle.once('exit', resolveExit); processHandle.kill(); })));
  const target = resolve(temp);
  if (!target.startsWith(resolve(tmpdir()) + sep) || !basename(target).startsWith('aimanager-s3-e2e-')) throw new Error('Unsafe cleanup target');
  rmSync(target, {recursive: true, force: true});
}
