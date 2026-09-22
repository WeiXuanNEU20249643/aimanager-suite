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
const temp = mkdtempSync(join(tmpdir(), 'aimanager-s4-e2e-'));
const output = join(root, 'artifacts'); mkdirSync(output, {recursive: true});
const python = process.env.AIMANAGER_TEST_PYTHON || join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const password = randomBytes(24).toString('base64url');
const env = {...process.env, AIMANAGER_DB: join(temp, 'test.sqlite3'), PYTHONIOENCODING: 'utf-8', PYTHONPATH: join(root, 'backend')};
const seed = spawnSync(python, ['tests/seed_e2e.py'], {cwd: join(root, 'backend'), env, input: JSON.stringify({password}), encoding: 'utf8', windowsHide: true});
if (seed.status !== 0) throw new Error(seed.stderr);
const backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '18003', '--no-access-log'], {cwd: join(root, 'backend'), env, stdio: 'pipe', windowsHide: true});
const frontend = spawn(process.execPath, [join(root, 'frontend/node_modules/vite/bin/vite.js'), '--port', '15176'], {cwd: join(root, 'frontend'), env: {...env, AIMANAGER_API_TARGET: 'http://127.0.0.1:18003'}, stdio: 'pipe', windowsHide: true});
let logs = ''; for (const processHandle of [backend, frontend]) { processHandle.stdout.on('data', chunk => logs += chunk); processHandle.stderr.on('data', chunk => logs += chunk); }
let browser;
async function untilServer(url) { for (let index = 0; index < 100; index++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise(resolveWait => setTimeout(resolveWait, 150)); } throw new Error('Server startup failed: ' + logs); }
async function login(page, username) {
  await page.goto('http://127.0.0.1:15176');
  await page.getByLabel('账号 / 邮箱').fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '登 录', exact: true}).click();
  await page.waitForURL('**/#overview?project=1');
}
async function apiResponse(page, path, method = 'GET', body) {
  return page.evaluate(async ({path, method, body}) => {
    const response = await fetch('/api' + path, {method, credentials: 'same-origin', headers: {
      'Content-Type': 'application/json', 'X-Requested-With': 'aimanager',
    }, body: body === undefined ? undefined : JSON.stringify(body)});
    return {status: response.status, data: response.status === 204 ? null : await response.json()};
  }, {path, method, body});
}
async function api(page, path, method = 'GET', body) {
  const response = await apiResponse(page, path, method, body);
  if (response.status < 200 || response.status >= 300) throw new Error(`${response.status}: ${JSON.stringify(response.data)}`);
  return response.data;
}

try {
  await untilServer('http://127.0.0.1:18003/api/health');
  await untilServer('http://127.0.0.1:15176');
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const adminContext = await browser.newContext({viewport: {width: 1480, height: 1040}});
  const admin = await adminContext.newPage();
  const errors = []; admin.on('pageerror', error => errors.push(error.message));
  await login(admin, 'qa_admin');

  let requirement = await api(admin, '/projects/1/requirements', 'POST', {title: '登记需求并创建任务',
    description: '产品负责人确认需求后建立实施任务。', source: 'Sprint 4 浏览器测试', story_role: '产品负责人',
    priority: 'Must', acceptance_criteria: '用例图可追溯到需求与任务。'});
  const acceptance = await api(admin, '/projects/1/requirements', 'POST', {title: '提交并验收任务',
    description: '执行成员提交工作，项目管理员确认验收。', source: 'Sprint 4 浏览器测试', story_role: '项目管理员',
    priority: 'Must', acceptance_criteria: '时序图按已保存步骤展示。'});
  const taskOne = await api(admin, '/projects/1/tasks', 'POST', {title: '实现需求转任务', requirement_id: requirement.id, owner_id: 2, sprint: 'S4'});
  const taskTwo = await api(admin, '/projects/1/tasks', 'POST', {title: '实现任务验收', requirement_id: acceptance.id, owner_id: 2, sprint: 'S4'});
  const center = await api(admin, '/projects/1/uml');
  await api(admin, '/projects/1/uml/use-case/generate', 'POST', {source_version: center.source_version});
  const requirementScenario = await api(admin, '/projects/1/uml/scenarios', 'POST', {name: '需求转任务',
    description: '产品负责人从确认需求建立实施任务。', participants: ['产品负责人', '前端页面', '服务端 API', '任务服务'],
    messages: [
      {from_participant: '产品负责人', to_participant: '前端页面', label: '提交已确认需求', branch_condition: '', task_id: taskOne.id},
      {from_participant: '前端页面', to_participant: '服务端 API', label: '请求创建任务', branch_condition: '需求版本有效', task_id: taskOne.id},
      {from_participant: '服务端 API', to_participant: '任务服务', label: '保存来源关联', branch_condition: '', task_id: taskOne.id},
    ]});
  const acceptanceScenario = await api(admin, '/projects/1/uml/scenarios', 'POST', {name: '任务验收',
    description: '执行成员提交工作后由项目管理员验收。', participants: ['执行成员', '任务看板', '服务端 API', '项目管理员'],
    messages: [
      {from_participant: '执行成员', to_participant: '任务看板', label: '提交待验收', branch_condition: '', task_id: taskTwo.id},
      {from_participant: '任务看板', to_participant: '服务端 API', label: '保存状态版本', branch_condition: '状态转换合法', task_id: taskTwo.id},
      {from_participant: '项目管理员', to_participant: '服务端 API', label: '确认验收条件', branch_condition: '验收条件通过', task_id: taskTwo.id},
    ]});
  await api(admin, `/projects/1/uml/scenarios/${requirementScenario.id}/generate`, 'POST', {scenario_version: requirementScenario.version});
  await api(admin, `/projects/1/uml/scenarios/${acceptanceScenario.id}/generate`, 'POST', {scenario_version: acceptanceScenario.version});

  await admin.getByRole('button', {name: 'UML中心', exact: true}).click();
  await admin.getByText('2/2 个场景完整', {exact: true}).waitFor();
  assert.equal(await admin.locator('.preview-notice').count(), 0);
  await admin.getByRole('link', {name: requirement.id, exact: true}).first().waitFor();
  await admin.getByRole('link', {name: taskOne.id, exact: false}).first().waitFor();
  await admin.screenshot({path: join(output, 'sprint4-use-case.png'), fullPage: true});

  await admin.getByRole('tab', {name: '时序图', exact: true}).click();
  await admin.getByLabel('业务场景').selectOption(String(acceptanceScenario.id));
  await admin.getByText('确认验收条件', {exact: false}).waitFor();
  await admin.getByRole('link', {name: taskTwo.id, exact: true}).first().waitFor();
  await admin.screenshot({path: join(output, 'sprint4-sequence.png'), fullPage: true});

  const invalid = await apiResponse(admin, `/projects/1/uml/scenarios/${requirementScenario.id}`, 'PATCH', {
    name: requirementScenario.name, description: requirementScenario.description, version: requirementScenario.version,
    participants: requirementScenario.participants,
    messages: [{from_participant: '不存在参与者', to_participant: '前端页面', label: '错误步骤', branch_condition: '', task_id: taskOne.id}],
  });
  assert.equal(invalid.status, 422);
  assert.match(invalid.data.detail, /第1条消息/);
  const stillValid = await api(admin, `/projects/1/uml/scenarios/${requirementScenario.id}`);
  assert.equal(stillValid.latest_generation.version, 1);

  requirement = await api(admin, `/projects/1/requirements/${requirement.id}`, 'PATCH', {title: '登记需求并创建实施任务',
    description: requirement.description, source: requirement.source, story_role: requirement.story_role,
    priority: requirement.priority, acceptance_criteria: requirement.acceptance_criteria, version: requirement.version,
    reason: '验证来源变更后的重新生成'});
  await admin.getByRole('tab', {name: '用例图', exact: true}).click();
  await admin.reload();
  await admin.getByText('来源已变化', {exact: true}).waitFor();
  await admin.getByRole('button', {name: '重新生成用例图', exact: true}).click();
  await admin.getByText('来源一致', {exact: true}).waitFor();
  await admin.getByText('登记需求并创建实施任务', {exact: true}).waitFor();

  const observerContext = await browser.newContext({viewport: {width: 1280, height: 900}});
  const observer = await observerContext.newPage(); observer.on('pageerror', error => errors.push(error.message));
  await login(observer, 'qa_observer');
  await observer.getByRole('button', {name: 'UML中心', exact: true}).click();
  await observer.getByText('2/2 个场景完整', {exact: true}).waitFor();
  assert.equal(await observer.getByRole('button', {name: /生成用例图/}).count(), 0);
  await observer.getByRole('tab', {name: '时序图', exact: true}).click();
  assert.equal(await observer.getByRole('button', {name: '新建场景', exact: true}).count(), 0);
  assert.deepEqual(errors, []);
  await observerContext.close(); await adminContext.close();
  console.log('PASS: Sprint 4 structured use-case and sequence generation, regeneration, permissions and source traceability.');
} catch (error) {
  if (browser) {
    let index = 0;
    for (const context of browser.contexts()) for (const page of context.pages()) {
      if (await page.locator('input[type=password]').count() === 0) {
        await page.screenshot({path: join(output, `sprint4-failure-${index++}.png`), fullPage: true});
        console.error('Failure page:', page.url(), (await page.locator('body').innerText()).slice(-5000));
      }
    }
  }
  throw error;
} finally {
  if (browser) await browser.close();
  await Promise.all([backend, frontend].map(processHandle => new Promise(resolveExit => { if (processHandle.exitCode !== null) return resolveExit(); processHandle.once('exit', resolveExit); processHandle.kill(); })));
  const target = resolve(temp);
  if (!target.startsWith(resolve(tmpdir()) + sep) || !basename(target).startsWith('aimanager-s4-e2e-')) throw new Error('Unsafe cleanup target');
  rmSync(target, {recursive: true, force: true});
}
