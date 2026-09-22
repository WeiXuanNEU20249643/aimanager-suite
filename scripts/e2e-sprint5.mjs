import {createRequire} from 'node:module';
import {spawn, spawnSync} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtempSync, mkdirSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve, join, sep, basename} from 'node:path';
import {randomBytes} from 'node:crypto';
import assert from 'node:assert/strict';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = resolve(import.meta.dirname, '..');
const temp = mkdtempSync(join(tmpdir(), 'aimanager-s5-e2e-'));
const output = join(root, 'artifacts'); mkdirSync(output, {recursive: true});
const python = process.env.AIMANAGER_TEST_PYTHON || join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const password = randomBytes(24).toString('base64url');

const modelServer = createServer(async (request, response) => {
  const chunks = []; for await (const chunk of request) chunks.push(chunk);
  const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const capability = payload.messages[0].content.match(/AIMANAGER_CAPABILITY=([^\n]+)/)?.[1];
  const source = JSON.parse(payload.messages[1].content);
  let result;
  if (capability === 'prd_breakdown') {
    result = {stories: [{local_id: 'STORY-1', role: '产品负责人', story: '建立发布审批',
      acceptance_criteria: ['给定待发布版本，审批通过后允许发布'], source_paragraph: source.prd_text,
      priority: 'Must', tasks: [
        {local_id: 'TASK-1', title: '实现审批接口', description: '保存审批决定', estimate_hours: 8, required_skills: ['后端'], depends_on: []},
        {local_id: 'TASK-2', title: '实现审批页面', description: '展示审批状态', estimate_hours: 6, required_skills: ['前端'], depends_on: ['TASK-1']},
      ]}], ambiguous_items: [], unsupported_items: []};
  } else if (capability === 'progress_forecast') {
    result = {summary: `预计完成日期为 ${source.evidence.expected_completion_date}`,
      factors: [`有效历史 ${source.evidence.sample_count} 条`, `中位数 ${source.evidence.median_actual_estimate_ratio}`],
      confidence_limits: []};
  } else {
    result = {summary: '建议遵循依赖、技能和容量约束，不承诺全局最优', assignments: source.plan.proposals.map(item => ({
      task_id: item.task_id, reason: `${item.after_owner_name} 的技能和容量满足要求`, tradeoffs: ['保留锁定任务', '依赖优先'],
    }))};
  }
  const body = JSON.stringify({choices: [{message: {content: JSON.stringify(result)}}]});
  response.writeHead(200, {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body)});
  response.end(body);
});
await new Promise(resolveListen => modelServer.listen(19004, '127.0.0.1', resolveListen));

const env = {...process.env, AIMANAGER_DB: join(temp, 'test.sqlite3'), PYTHONIOENCODING: 'utf-8', PYTHONPATH: join(root, 'backend'),
  AIMANAGER_AI_ENDPOINT: 'http://127.0.0.1:19004/v1/chat/completions', AIMANAGER_AI_MODEL: 'e2e-structured-model',
  AIMANAGER_AI_API_KEY: randomBytes(24).toString('base64url')};
const seed = spawnSync(python, ['tests/seed_e2e.py'], {cwd: join(root, 'backend'), env, input: JSON.stringify({password}), encoding: 'utf8', windowsHide: true});
if (seed.status !== 0) throw new Error(seed.stderr);
const backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '18004', '--no-access-log'], {cwd: join(root, 'backend'), env, stdio: 'pipe', windowsHide: true});
const frontend = spawn(process.execPath, [join(root, 'frontend/node_modules/vite/bin/vite.js'), '--port', '15177'], {cwd: join(root, 'frontend'), env: {...env, AIMANAGER_API_TARGET: 'http://127.0.0.1:18004'}, stdio: 'pipe', windowsHide: true});
let logs = ''; for (const processHandle of [backend, frontend]) { processHandle.stdout.on('data', chunk => logs += chunk); processHandle.stderr.on('data', chunk => logs += chunk); }
let browser;
async function untilServer(url) { for (let index = 0; index < 100; index++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise(resolveWait => setTimeout(resolveWait, 150)); } throw new Error('Server startup failed: ' + logs); }
async function login(page, username) {
  await page.goto('http://127.0.0.1:15177');
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
  await untilServer('http://127.0.0.1:18004/api/health');
  await untilServer('http://127.0.0.1:15177');
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const adminContext = await browser.newContext({viewport: {width: 1480, height: 1100}});
  const admin = await adminContext.newPage();
  const errors = []; admin.on('pageerror', error => errors.push(error.message));
  await login(admin, 'qa_admin');

  const requirement = await api(admin, '/projects/1/requirements', 'POST', {title: 'Sprint 5 预测样本', description: '用于预测与排期', source: '浏览器测试', story_role: '项目经理', priority: 'Must', acceptance_criteria: '结果可复算'});
  await api(admin, '/projects/1/members/2/capacity', 'PATCH', {weekly_capacity_hours: 40, available_from: '2026-10-01', available_to: '2026-12-31', skill_tags: ['后端', '前端'], version: 0, reason: '配置测试容量'});
  async function createTask(title) { return api(admin, '/projects/1/tasks', 'POST', {title, requirement_id: requirement.id, owner_id: 2, sprint: 'S5'}); }
  async function planTask(task, estimated, actual, remaining, skills = [], locked = false) { return api(admin, `/projects/1/tasks/${task.id}/plan`, 'PATCH', {estimated_hours: estimated, actual_hours: actual, remaining_hours: remaining, planned_start: locked ? '2026-10-12' : null, planned_end: locked ? '2026-10-13' : null, plan_locked: locked, required_skills: skills, version: task.version, reason: '浏览器测试'}); }
  async function completeTask(task) { for (const status of ['进行中', '待验收', '已完成']) task = await api(admin, `/projects/1/tasks/${task.id}/status`, 'PATCH', {status, version: task.version, reason: '', acceptance_confirmed: status === '已完成'}); return task; }
  for (const [index, values] of [[1, [8, 8]], [2, [10, 15]], [3, [20, 30]]]) {
    let task = await createTask(`历史样本 ${index}`); task = await planTask(task, values[0], values[1], 0); await completeTask(task);
  }
  let activeTask = await createTask('待预测任务'); activeTask = await planTask(activeTask, 10, 0, 10, ['后端']);
  let lockedTask = await createTask('锁定承诺任务'); lockedTask = await planTask(lockedTask, 8, 0, 8, ['后端'], true);

  await admin.getByRole('button', {name: 'AI分析', exact: true}).click();
  await admin.getByText('AI 服务已连接', {exact: true}).waitFor();
  await admin.getByLabel('来源名称').fill('发布审批 PRD');
  await admin.getByLabel('PRD 原文').fill('发布前必须由产品负责人审批。');
  await admin.getByRole('button', {name: '生成需求拆解草案', exact: true}).click();
  await admin.getByLabel('故事 1 标题').waitFor();
  await admin.getByLabel('故事 1 标题').fill('建立可追溯发布审批');
  await admin.getByLabel('审查理由').fill('补充可追溯要求');
  await admin.getByRole('button', {name: '保存修改', exact: true}).click();
  await admin.getByText(/draft_edited|补充可追溯要求/).waitFor();
  await admin.waitForTimeout(250);
  await admin.getByLabel('审查理由').fill('来源与验收条件已核对');
  await admin.getByRole('button', {name: '确认并应用', exact: true}).click();
  await admin.getByText('已应用', {exact: true}).first().waitFor();
  const requirements = await api(admin, '/projects/1/requirements');
  assert.ok(requirements.some(item => item.title === '建立可追溯发布审批'));

  const forecastCard = admin.locator('.s5-feature').filter({hasText: '进度预测'});
  await forecastCard.getByLabel('预测基准日期').fill('2026-10-12');
  await forecastCard.getByRole('button', {name: '生成草案', exact: true}).click();
  await admin.getByText('有效历史样本').waitFor();
  await admin.locator('.s5-metrics').getByText('3', {exact: true}).waitFor();
  await admin.waitForTimeout(250);
  await admin.getByLabel('审查理由').fill('预测样本和计算过程已核对');
  await admin.getByRole('button', {name: '确认并应用', exact: true}).click();
  await admin.getByText('已应用', {exact: true}).first().waitFor();

  const scheduleCard = admin.locator('.s5-feature').filter({hasText: '智能排期'});
  await scheduleCard.getByLabel('排期起始日期').fill('2026-10-12');
  await scheduleCard.getByRole('button', {name: '生成草案', exact: true}).click();
  await admin.getByText('约束检查通过', {exact: true}).waitFor();
  await admin.getByText('锁定任务不移动', {exact: false}).waitFor();
  await admin.waitForTimeout(250);
  await admin.getByLabel('审查理由').fill('技能、容量、依赖和差异已核对');
  await admin.getByRole('button', {name: '确认并应用', exact: true}).click();
  await admin.getByText('已应用', {exact: true}).first().waitFor();
  await admin.screenshot({path: join(output, 'sprint5-ai-review.png'), fullPage: true});

  await admin.getByRole('button', {name: '甘特图', exact: true}).click();
  await admin.getByText('实现审批接口', {exact: true}).waitFor();
  await admin.screenshot({path: join(output, 'sprint5-gantt-applied.png'), fullPage: true});

  const observerContext = await browser.newContext({viewport: {width: 1280, height: 900}});
  const observer = await observerContext.newPage(); observer.on('pageerror', error => errors.push(error.message));
  await login(observer, 'qa_observer');
  await observer.getByRole('button', {name: 'AI分析', exact: true}).click();
  await observer.getByText('AI 调用与审查记录', {exact: true}).waitFor();
  assert.equal(await observer.getByRole('button', {name: '确认并应用', exact: true}).count(), 0);
  assert.deepEqual(errors, []);
  await observerContext.close(); await adminContext.close();
  console.log('PASS: Sprint 5 real HTTP AI call, review/edit/apply, forecast evidence, constrained schedule and read-only access.');
} catch (error) {
  if (browser) {
    let index = 0;
    for (const context of browser.contexts()) for (const page of context.pages()) {
      if (await page.locator('input[type=password]').count() === 0) {
        await page.screenshot({path: join(output, `sprint5-failure-${index++}.png`), fullPage: true});
        console.error('Failure page:', page.url(), (await page.locator('body').innerText()).slice(-5000));
      }
    }
  }
  throw error;
} finally {
  if (browser) await browser.close();
  await Promise.all([backend, frontend].map(processHandle => new Promise(resolveExit => { if (processHandle.exitCode !== null) return resolveExit(); processHandle.once('exit', resolveExit); processHandle.kill(); })));
  await new Promise(resolveClose => modelServer.close(resolveClose));
  const target = resolve(temp);
  if (!target.startsWith(resolve(tmpdir()) + sep) || !basename(target).startsWith('aimanager-s5-e2e-')) throw new Error('Unsafe cleanup target');
  rmSync(target, {recursive: true, force: true});
}
