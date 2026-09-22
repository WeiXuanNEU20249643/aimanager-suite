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
const temp = mkdtempSync(join(tmpdir(), 'aimanager-s6-e2e-'));
const output = join(root, 'artifacts'); mkdirSync(output, {recursive: true});
const python = process.env.AIMANAGER_TEST_PYTHON || join(root, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const password = randomBytes(24).toString('base64url');

const modelServer = createServer(async (request, response) => {
  const chunks = []; for await (const chunk of request) chunks.push(chunk);
  const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const capability = payload.messages[0].content.match(/AIMANAGER_CAPABILITY=([^\n]+)/)?.[1];
  const source = JSON.parse(payload.messages[1].content);
  let result;
  if (capability === 'risk_analysis') {
    result = {summary: '已按确定性规则核对延期、阻塞、超载和预测日期。', risks: source.evidence.risks.map(item => ({
      risk_id: item.risk_id, severity: item.metric_value > item.threshold * 1.5 ? 'high' : 'medium',
      recommendation: `处理 ${item.evidence}`, owner_id: item.owner_id || source.members[0].id,
      next_check_date: '2026-09-25',
    }))};
  } else if (capability === 'quality_analysis') {
    result = {summary: '代码、文档和测试报告均已按选定范围检查。', issues: source.artifacts.map((item, index) => ({
      issue_id: `QUALITY-${index + 1}`, artifact_type: item.artifact_type, file_name: item.file_name,
      location: item.content_scope, category: ['代码缺陷', '文档完整性', '测试覆盖缺口'][index],
      title: ['修复异常吞没', '补充环境变量说明', '补充超时覆盖'][index],
      evidence: item.content.split('\n')[0], impact: '可能影响交付质量和复现。',
      recommendation: '依据定位结果修复并由非作者复验。', task_kind: index === 1 ? 'improvement' : 'defect',
    }))};
  } else {
    const metric = source.evidence.metrics.find(item => item.value > 0) || source.evidence.metrics[0];
    result = source.evidence.data_sufficient ? {summary: '指标显示任务流转仍有优化空间。', bottlenecks: [{
      metric_key: metric.key, metric_value: metric.value, bottleneck: `${metric.label}为 ${metric.value}${metric.unit}`,
      recommendation: '缩小任务批次并提前核对依赖。', action_title: '缩小任务批次',
      owner_id: source.members[0].id, due_date: '2026-09-30', review_metric: `重新采集${metric.label}并与基线比较`,
    }]} : {summary: source.evidence.data_notice, bottlenecks: []};
  }
  const body = JSON.stringify({choices: [{message: {content: JSON.stringify(result)}}]});
  response.writeHead(200, {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body)});
  response.end(body);
});
await new Promise(resolveListen => modelServer.listen(19005, '127.0.0.1', resolveListen));

const env = {...process.env, AIMANAGER_DB: join(temp, 'test.sqlite3'), PYTHONIOENCODING: 'utf-8', PYTHONPATH: join(root, 'backend'),
  AIMANAGER_AI_ENDPOINT: 'http://127.0.0.1:19005/v1/chat/completions', AIMANAGER_AI_MODEL: 'sprint6-e2e-model',
  AIMANAGER_AI_API_KEY: randomBytes(24).toString('base64url')};
const seed = spawnSync(python, ['tests/seed_e2e.py'], {cwd: join(root, 'backend'), env, input: JSON.stringify({password}), encoding: 'utf8', windowsHide: true});
if (seed.status !== 0) throw new Error(seed.stderr);
const backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '18005', '--no-access-log'], {cwd: join(root, 'backend'), env, stdio: 'pipe', windowsHide: true});
const frontend = spawn(process.execPath, [join(root, 'frontend/node_modules/vite/bin/vite.js'), '--port', '15178'], {cwd: join(root, 'frontend'), env: {...env, AIMANAGER_API_TARGET: 'http://127.0.0.1:18005'}, stdio: 'pipe', windowsHide: true});
let logs = ''; for (const processHandle of [backend, frontend]) { processHandle.stdout.on('data', chunk => logs += chunk); processHandle.stderr.on('data', chunk => logs += chunk); }
let browser;
async function untilServer(url) { for (let index = 0; index < 100; index++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise(resolveWait => setTimeout(resolveWait, 150)); } throw new Error('Server startup failed: ' + logs); }
async function login(page, username) {
  await page.goto('http://127.0.0.1:15178');
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
  await untilServer('http://127.0.0.1:18005/api/health');
  await untilServer('http://127.0.0.1:15178');
  browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const adminContext = await browser.newContext({viewport: {width: 1480, height: 1100}});
  const admin = await adminContext.newPage();
  const errors = []; admin.on('pageerror', error => errors.push(error.message));
  await login(admin, 'qa_admin');

  const requirement = await api(admin, '/projects/1/requirements', 'POST', {title: 'Sprint 6 闭环需求', description: '用于风险、质量和效率验证', source: '浏览器测试', story_role: '项目经理', priority: 'Must', acceptance_criteria: '证据可追溯且人工确认'});
  await api(admin, '/projects/1/members/2/capacity', 'PATCH', {weekly_capacity_hours: 20, available_from: '2026-09-01', available_to: '2026-12-31', skill_tags: ['后端'], version: 0, reason: '配置风险容量'});
  async function createTask(title, dueDate = null) { return api(admin, '/projects/1/tasks', 'POST', {title, requirement_id: requirement.id, owner_id: 2, due_date: dueDate, sprint: 'S6'}); }
  async function completeTask(task) { const statuses = task.status === '进行中' ? ['待验收', '已完成'] : ['进行中', '待验收', '已完成']; for (const status of statuses) task = await api(admin, `/projects/1/tasks/${task.id}/status`, 'PATCH', {status, version: task.version, reason: '形成效率样本', acceptance_confirmed: status === '已完成'}); return task; }
  let risky = await createTask('延期且超载的接口任务', '2026-09-10');
  risky = await api(admin, `/projects/1/tasks/${risky.id}/plan`, 'PATCH', {estimated_hours: 60, actual_hours: 4, remaining_hours: 60, planned_start: '2026-09-15', planned_end: '2026-10-10', plan_locked: false, required_skills: ['后端'], version: risky.version, reason: '风险场景'});
  await api(admin, `/projects/1/tasks/${risky.id}/blocker`, 'PATCH', {blocked: true, reason: '等待外部接口', version: risky.version});
  for (let index = 1; index <= 3; index++) {
    let task = await completeTask(await createTask(`效率样本 ${index}`));
    if (index === 1) {
      task = await api(admin, `/projects/1/tasks/${task.id}/reopen`, 'PATCH', {version: task.version, reason: '验收后发现遗漏'});
      await completeTask(task);
    }
  }

  await admin.getByRole('button', {name: 'AI分析', exact: true}).click();
  await admin.getByText('Sprint 6', {exact: true}).waitFor();
  await admin.getByText('AI 服务已连接', {exact: true}).waitFor();

  const riskCard = admin.locator('.s5-feature').filter({hasText: '风险预警'});
  await riskCard.getByLabel('风险分析日期').fill('2026-09-24');
  await riskCard.getByRole('button', {name: '生成草案', exact: true}).click();
  await admin.getByText(/项触发风险/).waitFor();
  await admin.getByLabel('审查理由').fill('规则、证据、负责人和复查日期已核对');
  await admin.getByRole('button', {name: '确认并应用', exact: true}).click();
  await admin.getByText('已应用', {exact: true}).first().waitFor();

  const qualityCard = admin.locator('.s6-quality-input');
  await qualityCard.getByLabel('承接需求', {exact: true}).selectOption(requirement.id);
  await qualityCard.getByLabel('负责人', {exact: true}).selectOption('2');
  await qualityCard.getByLabel('截止日', {exact: true}).fill('2026-09-30');
  const qualityInputs = [
    ['代码片段', 'service.py', 'abc123', '10-18行', 'except Exception: pass\nreturn result'],
    ['需求或说明文档', 'README.md', 'v2', '运行说明', '启动服务后访问页面。\n未说明环境变量。'],
    ['测试报告', 'report.txt', 'run-7', '失败与覆盖', 'FAILED test_timeout\ncoverage 61%'],
  ];
  for (const [label, file, version, scope, content] of qualityInputs) {
    await admin.getByLabel(`${label}文件名`, {exact: true}).fill(file);
    await admin.getByLabel(`${label}版本`, {exact: true}).fill(version);
    await admin.getByLabel(`${label}内容范围`, {exact: true}).fill(scope);
    await admin.getByLabel(`${label}内容`, {exact: true}).fill(content);
  }
  await admin.getByRole('button', {name: '生成质量分析草案', exact: true}).click();
  await admin.getByText('3 项待核实问题', {exact: true}).waitFor();
  await admin.getByLabel('审查理由').fill('三类输入版本、范围和逐字证据已人工核实');
  await admin.getByRole('button', {name: '确认并应用', exact: true}).click();
  await admin.getByText('已应用', {exact: true}).first().waitFor();
  const tasks = await api(admin, '/projects/1/tasks');
  assert.ok(tasks.some(item => item.title === '修复异常吞没'));
  assert.ok(tasks.some(item => item.title === '补充环境变量说明'));

  const efficiencyCard = admin.locator('.s5-feature').filter({hasText: '效率优化'});
  await efficiencyCard.getByLabel('效率分析日期').fill('2026-09-24');
  await efficiencyCard.getByRole('button', {name: '生成草案', exact: true}).click();
  await admin.getByText('参与计算的任务记录与覆盖期', {exact: true}).waitFor();
  await admin.getByLabel('审查理由').fill('指标记录、覆盖期和流程建议已核对');
  await admin.getByRole('button', {name: '确认并应用', exact: true}).click();
  await admin.getByText('已应用', {exact: true}).first().waitFor();

  await admin.waitForTimeout(1500);
  const action = admin.locator('.s6-action-list article').first();
  await action.getByLabel(/当前指标/).fill('0');
  await action.getByLabel(/复核说明/).fill('重新采集指标并由非作者复核，已经优于创建基线');
  await admin.waitForTimeout(250);
  assert.equal(await action.getByLabel(/当前指标/).inputValue(), '0');
  assert.ok((await action.getByLabel(/复核说明/).inputValue()).includes('优于创建基线'));
  await action.getByRole('button', {name: '复核并关闭', exact: true}).click();
  await admin.locator('.s6-action-list').getByText('已完成', {exact: true}).waitFor();
  await admin.screenshot({path: join(output, 'sprint6-risk-quality-efficiency.png'), fullPage: true});

  const observerContext = await browser.newContext({viewport: {width: 1280, height: 900}});
  const observer = await observerContext.newPage(); observer.on('pageerror', error => errors.push(error.message));
  await login(observer, 'qa_observer');
  await observer.getByRole('button', {name: 'AI分析', exact: true}).click();
  await observer.getByText('风险与效率改进行动', {exact: true}).waitFor();
  assert.equal(await observer.getByRole('button', {name: '生成草案', exact: true}).count(), 6);
  assert.equal(await observer.getByRole('button', {name: '确认并应用', exact: true}).count(), 0);
  assert.deepEqual(errors, []);
  await observerContext.close(); await adminContext.close();
  console.log('PASS: Sprint 6 risk, quality, efficiency, reviewed application, measurable action closure and observer access.');
} catch (error) {
  if (browser) {
    let index = 0;
    for (const context of browser.contexts()) for (const page of context.pages()) {
      if (await page.locator('input[type=password]').count() === 0) {
        await page.screenshot({path: join(output, `sprint6-failure-${index++}.png`), fullPage: true});
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
  if (!target.startsWith(resolve(tmpdir()) + sep) || !basename(target).startsWith('aimanager-s6-e2e-')) throw new Error('Unsafe cleanup target');
  rmSync(target, {recursive: true, force: true});
}
