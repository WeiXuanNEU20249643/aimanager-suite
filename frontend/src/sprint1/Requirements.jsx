import React, {useState} from 'react';
import {PageTitle, Card, SectionHead, PrimaryButton, GhostButton, Tag, icons} from '../components';
import {projectApi} from '../api';
import {can, useResource, dateTime, navigate} from './shared';
import {Empty, ErrorNotice, Field, Modal, ResourceState} from './ui';

const priorityTone = {Must: 'red', Should: 'orange', Could: 'blue', "Won't": 'gray'};

export function Requirements({project, route}) {
  const [query, setQuery] = useState('');
  const [editor, setEditor] = useState(null);
  const list = useResource(signal => projectApi(project.id, '/requirements?q=' + encodeURIComponent(query), {signal}), [project.id, query]);
  const detail = useResource(async signal => {
    if (!route.id) return null;
    const item = await projectApi(project.id, '/requirements/' + encodeURIComponent(route.id), {signal});
    const [progress, versions] = await Promise.all([
      can(project, 'task.read') ? projectApi(project.id, `/requirements/${encodeURIComponent(route.id)}/progress`, {signal}) : Promise.resolve(null),
      can(project, 'requirement.history') ? projectApi(project.id, `/requirements/${encodeURIComponent(route.id)}/versions`, {signal}) : Promise.resolve([]),
    ]);
    return {item, progress, versions};
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
        {can(project, 'requirement.history') && <><SectionHead title="版本历史"/><div className="version-history">{detail.data.versions.map(version => <details key={version.version} open={version.version === selected.version}><summary><b>v{version.version}</b><span>{version.reason}</span></summary><p>{version.changed_by_name}{version.changed_at ? ` · ${dateTime(version.changed_at)}` : ''}</p><p>{version.title} · {version.priority}</p><p className="long-text">{version.acceptance_criteria}</p></details>)}</div></>}
      </> : <Empty>选择需求查看详情</Empty>}</ResourceState></Card>
    </div>
    {editor && <RequirementForm project={project} requirement={editor.item} onClose={() => setEditor(null)} onSaved={saved => {setEditor(null); setQuery(''); refresh(); navigate('requirements/' + saved.id, project.id);}}/>}
  </>;
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
