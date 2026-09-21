import React, {useState} from 'react';
import {PageTitle, Card, SectionHead, PrimaryButton, GhostButton, Tag, icons} from '../components';
import {projectApi} from '../api';
import {can, useResource, dateTime, navigate} from './shared';
import {Empty, ErrorNotice, Field, Modal, ResourceState} from './ui';

const priorityTone = {Must: 'red', Should: 'orange', Could: 'blue', "Won't": 'gray'};

export function Requirements({project, route}) {
  const [query, setQuery] = useState('');
  const [editor, setEditor] = useState(null);
  const [planner, setPlanner] = useState(null);
  const [planNotice, setPlanNotice] = useState(null);
  const list = useResource(signal => projectApi(project.id, '/requirements?q=' + encodeURIComponent(query), {signal}), [project.id, query]);
  const detail = useResource(async signal => {
    if (!route.id) return null;
    const item = await projectApi(project.id, '/requirements/' + encodeURIComponent(route.id), {signal});
    const [progress, versions, planningImpact] = await Promise.all([
      can(project, 'task.read') ? projectApi(project.id, `/requirements/${encodeURIComponent(route.id)}/progress`, {signal}) : Promise.resolve(null),
      can(project, 'requirement.history') ? projectApi(project.id, `/requirements/${encodeURIComponent(route.id)}/versions`, {signal}) : Promise.resolve([]),
      can(project, 'task.read') ? projectApi(project.id, `/requirements/${encodeURIComponent(route.id)}/planning-impact`, {signal}) : Promise.resolve(null),
    ]);
    return {item, progress, versions, planningImpact};
  }, [project.id, route.id, project.role, project.role_id]);
  const writable = can(project, 'requirement.write');
  const refresh = () => { list.reload(); detail.reload(); };
  const selected = detail.data?.item;
  return <>
    <PageTitle title="需求管理" subtitle="维护优先级、可测验收条件与不可覆盖的版本记录。" actions={writable && <PrimaryButton onClick={() => setEditor({mode: 'create'})}>新建需求</PrimaryButton>}/>
    <Card className="filters"><div className="search-box"><icons.Search size={16}/><input aria-label="搜索需求" placeholder="搜索 REQ-ID 或关键词…" value={query} onChange={e => setQuery(e.target.value)}/></div><GhostButton onClick={refresh}>刷新</GhostButton></Card>
    <div className="split s1-split">
      <Card className="req-table"><SectionHead title={`需求列表${list.data ? `（共 ${list.data.length} 条）` : ''}`}/><ResourceState resource={list}>{list.data?.length ? <table><thead><tr><th>REQ-ID</th><th>标题</th><th>优先级</th><th>来源</th><th>版本</th></tr></thead><tbody>{list.data.map(r => <tr key={r.id} className={route.id === r.id ? 'selected' : ''}><td><a href={`#requirements/${r.id}?project=${project.id}`}>{r.id}</a></td><td><button className="text-link" onClick={() => navigate('requirements/' + r.id, project.id)}>{r.title}</button></td><td><Tag tone={priorityTone[r.priority]}>{r.priority}</Tag></td><td><Tag>{r.source}</Tag></td><td>v{r.version}</td></tr>)}</tbody></table> : <Empty>{query ? '没有匹配的需求，请调整关键词。' : '暂无需求，可登记第一条需求。'}</Empty>}</ResourceState></Card>
      <Card className="req-detail"><ResourceState resource={detail}>{selected ? <>
        <div className="detail-top"><Tag>{selected.id}</Tag><div className="detail-actions">{writable && <GhostButton onClick={() => setEditor({mode: 'edit', item: selected})}>编辑需求</GhostButton>}<GhostButton onClick={() => navigate('requirements', project.id)}>关闭详情</GhostButton></div></div>
        <h2>{selected.title}</h2><div className="tagline"><Tag tone={priorityTone[selected.priority]}>{selected.priority}</Tag><Tag>来源 {selected.source}</Tag><Tag tone="green">版本 {selected.version}</Tag></div>
        <div className="version-line">创建人：{selected.creator_name}<span>{dateTime(selected.created_at)}</span></div>
        <SectionHead title="需求描述"/><p className="long-text">{selected.description}</p>
        <SectionHead title="验收条件"/><p className="long-text acceptance-text">{selected.acceptance_criteria}</p>
        {writable && <PrimaryButton onClick={() => navigate('kanban/new', project.id, selected.id)}>从此需求创建任务</PrimaryButton>}
        {detail.data.progress && <><SectionHead title={`关联任务 · ${detail.data.progress.completed_count}/${detail.data.progress.active_count} 已完成`}/>
        {detail.data.progress.tasks.length ? <div className="requirement-task-list">{detail.data.progress.tasks.map(task => <a key={task.id} href={`#kanban/${task.id}?project=${project.id}`}><b>{task.id} · {task.title}</b><span>{task.owner_name || '未分配'} · {task.cancelled ? '已取消' : task.status}{task.review_required ? ' · 待复核' : ''}</span></a>)}</div> : <Empty>暂无关联任务</Empty>}</>}
        {detail.data.planningImpact && <PlanningImpact project={project} impact={detail.data.planningImpact} notice={planNotice} onReplan={() => {setPlanNotice(null); setPlanner(detail.data.planningImpact);}}/>}
        {can(project, 'requirement.history') && <><SectionHead title="版本历史"/><div className="version-history">{detail.data.versions.map(version => <details key={version.version} open={version.version === selected.version}><summary><b>v{version.version}</b><span>{version.reason}</span></summary><p>{version.changed_by_name}{version.changed_at ? ` · ${dateTime(version.changed_at)}` : ''}</p><p>{version.title} · {version.priority}</p><p className="long-text">{version.acceptance_criteria}</p></details>)}</div></>}
      </> : <Empty>选择需求查看详情</Empty>}</ResourceState></Card>
    </div>
    {editor && <RequirementForm project={project} requirement={editor.item} onClose={() => setEditor(null)} onSaved={saved => {setEditor(null); setQuery(''); refresh(); navigate('requirements/' + saved.id, project.id);}}/>}
    {planner && <ReplanForm project={project} requirement={selected} impact={planner} onClose={() => setPlanner(null)} onFinished={result => {setPlanner(null); setPlanNotice(result); refresh();}}/>}
  </>;
}

function PlanningImpact({project, impact, notice, onReplan}) {
  const latest = impact.latest_run;
  return <div className="s3-planning-impact"><SectionHead title={`排期影响 · ${impact.impacted_task_count} 项`} right={project.role === 'admin' && impact.impacted_task_count > 0 && <GhostButton onClick={onReplan}>确认并重新排期</GhostButton>}/>
    <div className="s3-impact-summary"><span><b>{impact.movable.length}</b> 项可自动重排</span><span><b>{impact.preserved.length}</b> 项保留承诺日期</span><span><b>v{impact.plan.version}</b> 共享排期版本</span></div>
    {notice && <div className={notice.applied ? 's3-plan-result success' : 's3-plan-result warning'}><b>{notice.message}</b><span>排期版本 v{notice.plan_version} · 日期更新 {notice.changes.length} 项 · 冲突/提醒 {notice.conflicts.length} 项</span></div>}
    {impact.impacted_task_count ? <div className="s3-impact-list">{[...impact.movable.map(item => ({...item, mode:'movable'})), ...impact.preserved.map(item => ({...item, mode:'preserved'}))].map(item => <a key={item.id} href={`#kanban/${item.id}?project=${project.id}`}><span><b>{item.id} · {item.title}</b><small>{item.owner_name || '未分配'} · {item.planned_start && item.planned_end ? `${item.planned_start} 至 ${item.planned_end}` : '尚未完整排期'}</small></span><Tag tone={item.mode === 'movable' ? 'blue' : 'purple'}>{item.mode === 'movable' ? '可重排' : item.preserve_reason}</Tag></a>)}</div> : <Empty>此需求暂无有效关联任务，无需重排。</Empty>}
    {latest && <div className="s3-latest-run"><div><b>最近排期记录 · v{latest.plan_version}</b><Tag tone={latest.applied ? 'green' : 'orange'}>{latest.applied ? '已应用' : '因冲突未应用'}</Tag></div><p>{latest.reason} · {latest.triggered_by_name} · {dateTime(latest.created_at)}</p>{latest.conflicts.length > 0 && <ul>{latest.conflicts.map((item, index) => <li key={`${item.task_id}-${index}`}>{item.task_id}：{item.message}</li>)}</ul>}</div>}
    {project.role !== 'admin' && impact.impacted_task_count > 0 && <p className="muted">当前为只读影响清单；全项目排期应用需由内置管理员确认。</p>}
  </div>;
}

function ReplanForm({project, requirement, impact, onClose, onFinished}) {
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try { onFinished(await projectApi(project.id, `/requirements/${requirement.id}/replan`, {method: 'POST', body: {
      requirement_version: impact.requirement_version, plan_version: impact.plan.version, reason: values.reason,
    }})); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={`确认需求影响并重排 · ${requirement.id}`} onClose={onClose}><form onSubmit={submit}><p className="muted">系统将按依赖顺序、成员可用时段与每周容量计算。已完成、进行中、待验收或已锁定任务不会被静默移动；出现必要数据缺失时不会部分更新。</p><div className="s3-impact-summary"><span><b>{impact.movable.length}</b> 项可重排</span><span><b>{impact.preserved.length}</b> 项保留</span><span><b>v{impact.plan.version}</b> 当前排期</span></div><Field label="确认原因"><textarea name="reason" required maxLength={10000} rows={4} placeholder="说明已核对的工作量、优先级或依赖变化"/></Field><ErrorNotice error={error}/><div className="editor-actions"><GhostButton type="button" onClick={onClose}>取消</GhostButton><PrimaryButton icon={null} disabled={busy}>{busy ? '计算并保存中…' : '确认并重新排期'}</PrimaryButton></div></form></Modal>;
}

function RequirementForm({project, requirement, onClose, onSaved}) {
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const body = Object.fromEntries(new FormData(event.currentTarget));
    if (requirement) body.version = requirement.version;
    try { onSaved(await projectApi(project.id, '/requirements' + (requirement ? '/' + requirement.id : ''), {method: requirement ? 'PATCH' : 'POST', body})); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={requirement ? `编辑需求 · ${requirement.id}` : '新建需求'} onClose={onClose}><form onSubmit={submit}>
    <Field label="标题"><input name="title" defaultValue={requirement?.title || ''} required maxLength={200}/></Field>
    <Field label="需求描述"><textarea name="description" defaultValue={requirement?.description || ''} required maxLength={10000} rows={5}/></Field>
    <div className="s1-form-grid"><Field label="来源"><input name="source" defaultValue={requirement?.source || ''} required maxLength={200}/></Field><Field label="优先级"><select name="priority" defaultValue={requirement?.priority || 'Must'}>{['Must','Should','Could',"Won't"].map(value => <option key={value}>{value}</option>)}</select></Field></div>
    <Field label="验收条件"><textarea name="acceptance_criteria" defaultValue={requirement?.acceptance_criteria === '待补充验收条件' ? '' : requirement?.acceptance_criteria || ''} required maxLength={10000} rows={5} placeholder="写明可测试的给定条件、操作和预期结果"/></Field>
    {requirement && <Field label="变更原因"><textarea name="reason" required maxLength={10000} rows={3} placeholder="说明本次需求变更的原因和影响"/></Field>}
    <ErrorNotice error={error}/><div className="editor-actions"><GhostButton type="button" onClick={onClose}>取消</GhostButton><PrimaryButton icon={null} disabled={busy}>{busy ? '保存中…' : requirement ? '保存新版本' : '保存需求'}</PrimaryButton></div>
  </form></Modal>;
}
