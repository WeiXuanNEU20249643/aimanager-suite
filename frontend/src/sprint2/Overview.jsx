import React, {useState} from 'react';
import {PageTitle, Card, Metric, SectionHead, PrimaryButton, GhostButton, Progress, Tag, icons} from '../components';
import {projectApi} from '../api';
import {can, dateTime, statuses, tones, useResource} from '../sprint1/shared';
import {Empty, ErrorNotice, Field, Modal, ResourceState} from '../sprint1/ui';

export function Overview({project}) {
  const [editor, setEditor] = useState(null);
  const [capacityEditor, setCapacityEditor] = useState(null);
  const resource = useResource(async signal => {
    const [statistics, milestones, tasks, requirements, members] = await Promise.all([
      can(project, 'statistics.read') ? projectApi(project.id, '/statistics/completion', {signal}) : Promise.resolve(null),
      can(project, 'milestone.read') ? projectApi(project.id, '/milestones', {signal}) : Promise.resolve([]),
      can(project, 'task.read') ? projectApi(project.id, '/tasks', {signal}) : Promise.resolve([]),
      can(project, 'requirement.read') ? projectApi(project.id, '/requirements', {signal}) : Promise.resolve([]),
      projectApi(project.id, '/members', {signal}),
    ]);
    return {statistics, milestones, tasks, requirements, members};
  }, [project.id, project.role, project.role_id]);
  const milestoneWritable = can(project, 'milestone.write');
  const data = resource.data;
  const blocked = data?.tasks.filter(task => task.manually_blocked || task.dependency_blocked).length || 0;
  return <>
    <PageTitle title="项目概览" subtitle="状态、完成率和里程碑均来自当前项目的实时任务数据。" actions={<>{milestoneWritable && <PrimaryButton onClick={() => setEditor({})}>新建里程碑</PrimaryButton>}<GhostButton onClick={resource.reload}>刷新数据</GhostButton></>}/>
    <ResourceState resource={resource}>{data && <>
      <div className="metric-grid six"><Metric icon={icons.ClipboardList} label="需求总数" value={can(project, 'requirement.read') ? data.requirements.length : '—'} sub="按当前角色权限显示"/><Metric icon={icons.Database} label="有效任务" value={data.statistics ? data.statistics.active_total : '—'} sub={data.statistics ? `另有 ${data.statistics.cancelled_count} 项已取消` : '当前未包含取消项'}/><Metric icon={icons.CheckCircle2} label="已完成" value={data.statistics ? data.statistics.completed : '—'} sub="仅最终验收完成" tone="green"/><Metric icon={icons.TrendingUp} label="整体完成率" value={!data.statistics ? '—' : data.statistics.completion_rate == null ? '暂无任务' : `${data.statistics.completion_rate.toFixed(1)}%`} sub="已完成 ÷ 有效任务" tone="purple"/><Metric icon={icons.AlertTriangle} label="阻塞任务" value={can(project, 'task.read') ? blocked : '—'} sub="依赖阻塞与人工阻塞" tone={blocked ? 'red' : 'green'}/><Metric icon={icons.Target} label="里程碑" value={can(project, 'milestone.read') ? data.milestones.length : '—'} sub="按目标日期排序"/></div>
      <div className="s2-overview-grid"><Card><SectionHead title="任务状态概览" right={can(project, 'task.read') && <a href={`#tasks?project=${project.id}`}>查看全部任务 →</a>}/>{data.statistics ? <><div className="overview-status-list">{statuses.map(status => <a key={status} href={`#tasks?project=${project.id}&status=${encodeURIComponent(status)}`}><Tag tone={tones[status]}>{status}</Tag><b>{data.statistics.status_counts[status]}</b><span>查看同口径明细 →</span></a>)}<a href={`#tasks?project=${project.id}&cancelled=only`}><Tag tone="gray">已取消</Tag><b>{data.statistics.cancelled_count}</b><span>查看取消依据 →</span></a></div>{data.statistics.active_total ? <><div className="completion-bar"><Progress value={data.statistics.completion_rate || 0} tone="green"/></div><p className="muted">四状态合计 {Object.values(data.statistics.status_counts).reduce((sum, value) => sum + value, 0)}，与有效任务总数 {data.statistics.active_total} 一致；取消项单列且不进入分母。</p></> : <Empty>暂无有效任务，完成率不显示为 0。</Empty>}</> : <Empty>当前角色没有查看项目统计的权限。</Empty>}</Card>
      <Card><SectionHead title="里程碑完成情况" right={milestoneWritable && <GhostButton onClick={() => setEditor({})}>新增</GhostButton>}/>{can(project, 'milestone.read') ? data.milestones.length ? <div className="milestone-list">{data.milestones.map(milestone => { const linked = data.tasks.filter(task => task.milestone_id === milestone.id); return <div key={milestone.id}><div><span><b>{milestone.name}</b><small>目标日期 {milestone.target_date}</small></span><Tag tone={milestone.completion_rate === 100 ? 'green' : 'blue'}>{milestone.completion_rate == null ? '暂无任务' : `${milestone.completion_rate.toFixed(1)}%`}</Tag></div><Progress value={milestone.completion_rate || 0} tone={milestone.completion_rate === 100 ? 'green' : 'blue'}/><p>{milestone.completed_count}/{milestone.active_count} 已完成{milestoneWritable && <button className="text-link" onClick={() => setEditor(milestone)}>编辑里程碑</button>}</p>{can(project, 'task.read') && <div className="milestone-task-links">{linked.length ? linked.map(task => <a key={task.id} href={`#kanban/${task.id}?project=${project.id}`}>{task.id} · {task.title}</a>) : <span>暂无关联任务</span>}</div>}</div>;})}</div> : <Empty>暂无里程碑，可创建第一项。</Empty> : <Empty>当前角色没有查看里程碑的权限。</Empty>}</Card></div>
      <Card className="capacity-card"><SectionHead title="成员容量与技能"/><p className="muted">容量按小时记录，不使用任务数量替代工作量；未配置项明确显示。</p><table className="capacity-table"><thead><tr><th>成员</th><th>每周容量</th><th>可用时段</th><th>技能标签</th><th>版本与更新</th><th>操作</th></tr></thead><tbody>{data.members.map(member => <tr key={member.id}><td>{member.name}<small>{member.role_name}</small></td><td>{member.weekly_capacity_hours == null ? '未配置' : `${member.weekly_capacity_hours} 小时`}</td><td>{member.available_from || '未设置'} 至 {member.available_to || '未设置'}</td><td>{member.skill_tags.length ? member.skill_tags.map(tag => <Tag key={tag}>{tag}</Tag>) : '未配置'}</td><td>{member.capacity_version ? `v${member.capacity_version} · ${member.capacity_updated_by_name} · ${dateTime(member.capacity_updated_at)}` : '尚无记录'}</td><td>{can(project, 'task.write') ? <GhostButton onClick={() => setCapacityEditor(member)}>维护容量</GhostButton> : '只读'}</td></tr>)}</tbody></table></Card>
    </>}</ResourceState>
    {editor && <MilestoneForm project={project} milestone={editor.id ? editor : null} onClose={() => setEditor(null)} onSaved={() => {setEditor(null); resource.reload();}}/>}
    {capacityEditor && <CapacityForm project={project} member={capacityEditor} onClose={() => setCapacityEditor(null)} onSaved={() => {setCapacityEditor(null); resource.reload();}}/>}
  </>;
}

function CapacityForm({project, member, onClose, onSaved}) {
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const body = {weekly_capacity_hours: Number(values.weekly_capacity_hours), available_from: values.available_from || null, available_to: values.available_to || null, skill_tags: values.skill_tags.split(',').map(value => value.trim()).filter(Boolean), version: member.capacity_version, reason: values.reason};
    try { await projectApi(project.id, `/members/${member.id}/capacity`, {method: 'PATCH', body}); onSaved(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={`维护成员容量 · ${member.name}`} onClose={onClose}><form onSubmit={submit}><Field label="每周容量 小时"><input aria-label="每周容量" name="weekly_capacity_hours" type="number" min="0" max="168" step="0.25" defaultValue={member.weekly_capacity_hours ?? 20} required/></Field><div className="s1-form-grid"><Field label="可用开始日期"><input aria-label="可用开始日期" name="available_from" type="date" defaultValue={member.available_from || ''}/></Field><Field label="可用结束日期"><input aria-label="可用结束日期" name="available_to" type="date" defaultValue={member.available_to || ''}/></Field></div><Field label="技能标签"><input aria-label="技能标签" name="skill_tags" defaultValue={member.skill_tags.join(', ')} placeholder="用英文逗号分隔，例如 React, FastAPI"/></Field><Field label="变更原因"><textarea aria-label="容量变更原因" name="reason" maxLength={2000} rows={3} placeholder="可选，便于后续核对"/></Field><ErrorNotice error={error}/><div className="editor-actions"><GhostButton type="button" onClick={onClose}>取消</GhostButton><PrimaryButton icon={null} disabled={busy}>{busy ? '保存中…' : '保存容量'}</PrimaryButton></div></form></Modal>;
}

function MilestoneForm({project, milestone, onClose, onSaved}) {
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const body = Object.fromEntries(new FormData(event.currentTarget));
    if (milestone) body.version = milestone.version;
    try { await projectApi(project.id, '/milestones' + (milestone ? '/' + milestone.id : ''), {method: milestone ? 'PATCH' : 'POST', body}); onSaved(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={milestone ? `编辑里程碑 · ${milestone.name}` : '新建里程碑'} onClose={onClose}><form onSubmit={submit}><Field label="里程碑名称"><input name="name" defaultValue={milestone?.name || ''} required maxLength={200}/></Field><Field label="目标日期"><input type="date" name="target_date" defaultValue={milestone?.target_date || ''} required/></Field><ErrorNotice error={error}/><div className="editor-actions"><GhostButton type="button" onClick={onClose}>取消</GhostButton><PrimaryButton icon={null} disabled={busy}>{busy ? '保存中…' : '保存里程碑'}</PrimaryButton></div></form></Modal>;
}
