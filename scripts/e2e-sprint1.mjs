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
const temp = mkdtempSync(join(tmpdir(), 'aimanager-e2e-'));
const output = join(root, 'artifacts'); mkdirSync(output, {recursive:true});
const python = process.env.AIMANAGER_TEST_PYTHON || join(root,'backend','.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const password = randomBytes(24).toString('base64url');
const env = {...process.env, AIMANAGER_DB:join(temp,'test.sqlite3'), PYTHONIOENCODING:'utf-8', PYTHONPATH:join(root,'backend')};
const seed = spawnSync(python, ['tests/seed_e2e.py'], {cwd:join(root,'backend'), env, input:JSON.stringify({password}), encoding:'utf8', windowsHide:true});
if(seed.status!==0) throw new Error(seed.stderr);
const backend = spawn(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','18000','--no-access-log'],{cwd:join(root,'backend'),env,stdio:'pipe',windowsHide:true});
const frontend = spawn(process.execPath,[join(root,'frontend/node_modules/vite/bin/vite.js'),'--port','15173'],{cwd:join(root,'frontend'),env:{...env,AIMANAGER_API_TARGET:'http://127.0.0.1:18000'},stdio:'pipe',windowsHide:true});
let logs=''; for(const proc of [backend,frontend]) {proc.stdout.on('data',d=>logs+=d);proc.stderr.on('data',d=>logs+=d);}
let browser;
async function untilServer(url) { for(let n=0;n<100;n++){try{if((await fetch(url)).ok)return;}catch{} await new Promise(r=>setTimeout(r,150));}throw new Error('Server startup failed: '+logs); }
try {
  await untilServer('http://127.0.0.1:18000/api/health'); await untilServer('http://127.0.0.1:15173');
  browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})});
  const context = await browser.newContext({viewport:{width:1480,height:1040}});
  const page = await context.newPage();
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  async function login(p,username) {await p.goto('http://127.0.0.1:15173');await p.getByLabel('账号 / 邮箱').fill(username);await p.getByLabel('密码',{exact:true}).fill(password);await p.getByRole('button',{name:'登 录',exact:true}).click();await p.getByLabel('当前项目').selectOption('1');await p.waitForURL('**/#overview?project=1');}
  await login(page,'qa_admin');
  await page.getByRole('button',{name:'成员与权限',exact:true}).click();
  await page.getByRole('button',{name:'添加成员',exact:true}).click();
  await page.getByLabel('已有账号').fill('qa_new');
  await page.getByRole('button',{name:'保存成员'}).click();
  await page.getByText('待加入成员',{exact:true}).waitFor();
  await page.getByRole('button',{name:'需求管理',exact:true}).click();
  await page.getByRole('button',{name:'新建需求',exact:true}).click();
  await page.getByLabel('标题',{exact:true}).fill('浏览器测试需求');
  await page.getByLabel('需求描述',{exact:true}).fill('验证真实数据库创建与稳定详情地址。');
  await page.getByLabel('来源',{exact:true}).fill('自动化测试样本');
  await page.getByLabel('验收条件',{exact:true}).fill('创建后可按稳定编号读取，并在刷新后保持一致。');
  await page.getByRole('button',{name:'保存需求'}).click();
  await page.getByRole('heading',{name:'浏览器测试需求',exact:true}).waitFor();
  const requirementUrl=page.url();
  assert.match(requirementUrl,/#requirements\/REQ-\d+\?project=1/);
  await page.reload(); await page.getByRole('heading',{name:'浏览器测试需求',exact:true}).waitFor();
  await page.getByRole('button',{name:'成员与权限',exact:true}).click();
  await page.getByRole('heading',{name:'成员与权限',exact:true}).waitFor();
  await page.goBack(); await page.getByRole('heading',{name:'浏览器测试需求',exact:true}).waitFor();
  await page.goForward(); await page.getByRole('heading',{name:'成员与权限',exact:true}).waitFor();
  await page.goto(requirementUrl); await page.getByRole('heading',{name:'浏览器测试需求',exact:true}).waitFor();
  const requirementRequests=/\/api\/projects\/1\/requirements(?:\/[^?]*)?(?:\?.*)?$/;
  await page.route(requirementRequests,route=>route.abort());
  await page.getByRole('button',{name:'刷新',exact:true}).click();
  await page.getByRole('alert').nth(1).waitFor();
  assert.equal(await page.getByRole('heading',{name:'浏览器测试需求',exact:true}).count(),0);
  await page.unroute(requirementRequests);
  await page.getByRole('button',{name:'刷新',exact:true}).click();
  await page.getByRole('heading',{name:'浏览器测试需求',exact:true}).waitFor();
  await page.getByLabel('搜索需求').fill('不存在的关键词'); await page.getByText('没有匹配的需求，请调整关键词。').waitFor();
  await page.getByLabel('搜索需求').fill('REQ-001'); await page.getByRole('link',{name:'REQ-001',exact:true}).waitFor();
  await page.screenshot({path:join(output,'sprint1-requirements.png'),fullPage:true});
  const observerContext=await browser.newContext({viewport:{width:1480,height:1040}});
  const observer=await observerContext.newPage(); await login(observer,'qa_observer');
  observer.on('pageerror',e=>errors.push(e.message));
  await observer.goto(requirementUrl); await observer.getByRole('heading',{name:'浏览器测试需求',exact:true}).waitFor();
  assert.equal(await observer.getByRole('button',{name:'新建需求',exact:true}).count(),0);
  assert.equal(await observer.getByRole('button',{name:'从此需求创建任务'}).count(),0);
  if(process.argv.includes('--full')) {
    // Task workflow is exercised after the task module is connected.
    await page.getByRole('button',{name:'从此需求创建任务'}).click();
    await page.getByLabel('任务标题',{exact:true}).fill('浏览器测试任务');
    await page.getByLabel('任务描述',{exact:true}).fill('任务完整闭环验证');
    await page.getByLabel('负责人',{exact:true}).selectOption('2');
    await page.getByLabel('截止日期',{exact:true}).fill('2026-10-01');
    await page.getByRole('button',{name:'创建任务',exact:true}).click();
    await page.getByRole('heading',{name:'浏览器测试任务',exact:true}).waitFor();
    const taskUrl=page.url();
    assert.match(taskUrl,/#kanban\/T-\d+\?project=1/);
    await page.getByRole('button',{name:'列表',exact:true}).click(); await page.getByRole('cell',{name:'浏览器测试任务',exact:true}).waitFor();
    await page.getByRole('button',{name:'看板',exact:true}).click();
    const memberContext=await browser.newContext({viewport:{width:1480,height:1040}}); const member=await memberContext.newPage(); member.on('pageerror',e=>errors.push(e.message));await login(member,'qa_member');await member.goto(taskUrl);
    await member.getByRole('button',{name:'编辑任务',exact:true}).click();
    await member.getByLabel('任务描述',{exact:true}).fill('成员修改后的任务描述');
    await member.getByLabel('所属 Sprint',{exact:true}).selectOption('S2');
    await member.getByRole('button',{name:'保存任务',exact:true}).click();
    await member.getByText('成员修改后的任务描述',{exact:true}).waitFor();
    await member.getByRole('button',{name:'开始任务',exact:true}).click();
    await member.getByRole('button',{name:'提交验收',exact:true}).click();
    await member.getByText('等待管理员最终验收。',{exact:true}).waitFor();
    assert.equal(await member.getByRole('button',{name:'验收完成',exact:true}).count(),0);
    await page.reload(); await page.getByLabel('我已核对关联需求，确认验收条件通过').check();
    await page.getByRole('button',{name:'验收完成',exact:true}).click();
    await page.getByText('任务已完成。',{exact:true}).waitFor();
    await page.getByRole('button',{name:'列表',exact:true}).click();
    await page.getByRole('cell',{name:'已完成',exact:true}).waitFor();
    await page.reload(); await page.getByText('任务已完成。',{exact:true}).waitFor();
    await page.getByRole('button',{name:'看板',exact:true}).click();
    await page.screenshot({path:join(output,'sprint1-kanban.png'),fullPage:true});
    await page.setViewportSize({width:1280,height:900});
    await page.screenshot({path:join(output,'sprint1-kanban-1280.png'),fullPage:true});
    await page.setViewportSize({width:1480,height:1040});
    await observer.goto(taskUrl); await observer.getByText('任务已完成。',{exact:true}).waitFor();
    assert.equal(await observer.getByRole('button',{name:'新建任务',exact:true}).count(),0);
    assert.equal(await observer.getByRole('button',{name:'编辑任务',exact:true}).count(),0);
    await page.getByLabel('当前项目').selectOption('2');
    await page.getByText('暂无任务，请先登记需求，再创建任务。',{exact:true}).waitFor();
    assert.equal(await page.getByText('浏览器测试任务',{exact:true}).count(),0);
    await page.getByLabel('当前项目').selectOption('1');
    await page.getByRole('button',{name:'成员与权限',exact:true}).click();
    await page.getByRole('row').filter({hasText:'qa_member'}).getByRole('button',{name:'移除',exact:true}).click();
    await page.getByRole('button',{name:'确认移除',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await member.reload();await member.getByText('暂无获授权项目，请联系管理员将您的账号加入项目。',{exact:true}).waitFor();
    await memberContext.close();
  }
  await page.getByRole('button',{name:'退出登录',exact:true}).click();await page.getByRole('button',{name:'登 录',exact:true}).waitFor();
  await page.goto(requirementUrl);await page.getByRole('button',{name:'登 录',exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  await observerContext.close(); await context.close();
  console.log(process.argv.includes('--full')?'PASS: full Sprint 1 browser workflow, roles, persistence, isolation and logout.':'PASS: login, members, requirement creation/search/deep-link/reload, observer UI and logout.');
} catch(error) {
  if(browser) {
    let index=0;
    for(const context of browser.contexts()) for(const page of context.pages()) {
      if(await page.locator('input[type=password]').count()===0) {
        await page.screenshot({path:join(output,`sprint1-failure-${index++}.png`),fullPage:true});
        console.error('Failure page:',page.url(),(await page.locator('body').innerText()).slice(-3500));
      }
    }
  }
  throw error;
} finally {
  if(browser) await browser.close();
  await Promise.all([backend,frontend].map(proc=>new Promise(r=>{if(proc.exitCode!==null)return r();proc.once('exit',r);proc.kill();})));
  // Verify the absolute cleanup target is the exact test directory under the OS temp root.
  const target=resolve(temp);
  if(!target.startsWith(resolve(tmpdir())+sep)||!basename(target).startsWith('aimanager-e2e-')) throw new Error('Unsafe cleanup target');
  rmSync(target,{recursive:true,force:true});
}
