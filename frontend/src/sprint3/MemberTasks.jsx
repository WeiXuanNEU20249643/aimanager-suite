import React, {useMemo, useState} from 'react';
import {PageTitle, Card, GhostButton, Metric, Progress, SectionHead, Tag, Avatar, icons} from '../components';
import {statuses, tones} from '../sprint1/shared';
import {Empty, ErrorNotice, Loading} from '../sprint1/ui';
import {taskHours, usePlanningData} from './shared';

export function MemberTasks({project}) {
  const resource = usePlanningData(project.id, 5000);
  const [owner, setOwner] = useState('all');
  const [status, setStatus] = useState('');
  const [sprint, setSprint] = useState('');
  const [query, setQuery] = useState('');
  const data = resource.data;
  const tasks = useMemo(() => (data?.tasks || []).filter(task => {
    const text = `${task.id} ${task.title} ${task.requirement_id}`.toLocaleLowerCase('zh-CN');
    return (!status || task.status === status) && (!sprint || task.sprint === sprint) &&
      (owner === 'all' || owner === 'unassigned' && task.owner_id == null || String(task.owner_id) === owner) &&
      (!query.trim() || text.includes(query.trim().toLocaleLowerCase('zh-CN')));
  }), [data, owner, status, sprint, query]);
  const groups = useMemo(() => {
    if (!data) return [];
    const memberGroups = data.members.map(member => ({...member, tasks: tasks.filter(task => task.owner_id === member.id)}));
    const unassignedTasks = tasks.filter(task => task.owner_id == null);
    if (unassignedTasks.length || owner === 'unassigned') memberGroups.push({id: 'unassigned', name: '未分配', active: true,
      role_name: '待协调', task_count: data.unassigned.task_count, workload_hours: data.unassigned.workload_hours,
      capacity_hours: null, load_percent: null, overloaded: false, skill_tags: [], tasks: unassignedTasks});
    return memberGroups.filter(group => owner === 'all' || String(group.id) === owner);
  }, [data, tasks, owner]);
  const teamCapacity = data?.members.reduce((sum, member) => sum + Number(member.capacity_hours || 0), 0) || 0;
  const assignedHours = data?.members.reduce((sum, member) => sum + Number(member.workload_hours || 0), 0) || 0;
  const overloaded = data?.members.filter(member => member.overloaded).length || 0;
  const averageLoad = data?.members.filter(member => member.load_percent != null);
  const averagePercent = averageLoad?.length ? averageLoad.reduce((sum, member) => sum + member.load_percent, 0) / averageLoad.length : null;
  return <>
    <PageTitle title="成员任务图" subtitle="按负责人查看同一批任务、计划日期和工时负荷；页面每 5 秒静默同步。" actions={<GhostButton icon={icons.RefreshCcw} onClick={resource.reload}>立即同步</GhostButton>}/>
    <div className="tabs"><a href={`#gantt?project=${project.id}`}>甘特图</a><a className="active" href={`#members?project=${project.id}`}>成员任务图</a></div>
    {resource.error && <div className="s3-sync-error"><ErrorNotice error={resource.error} retry={resource.reload}/><span>网络恢复后会重新读取服务端数据；当前页面不会用旧值覆盖新版本。</span></div>}
    {resource.loading && !data ? <Loading/> : data && <>
      <div className="s3-version-strip"><span>共享排期版本 <b>v{data.plan.version}</b></span><span>与看板共享任务 ID、状态、负责人和任务版本</span><span>自动刷新周期 5 秒 · {data.plan.updated_at ? `数据更新于 ${new Date(data.plan.updated_at).toLocaleTimeString('zh-CN', {hour12:false})}` : '等待首条变更'}</span></div>
      <Card className="s3-member-filters"><label><span>成员</span><select aria-label="成员筛选" value={owner} onChange={event => setOwner(event.target.value)}><option value="all">全部成员</option>{data.members.map(member => <option key={member.id} value={member.id}>{member.name}{member.active ? '' : '（已移除）'}</option>)}<option value="unassigned">未分配</option></select></label><label><span>状态</span><select aria-label="成员图状态筛选" value={status} onChange={event => setStatus(event.target.value)}><option value="">全部状态</option>{statuses.map(value => <option key={value}>{value}</option>)}</select></label><label><span>Sprint</span><select aria-label="成员图 Sprint 筛选" value={sprint} onChange={event => setSprint(event.target.value)}><option value="">全部 Sprint</option>{Array.from({length:6}, (_, index) => <option key={index}>S{index + 1}</option>)}</select></label><label className="s3-member-search"><span>任务关键词</span><div><icons.Search size={15}/><input aria-label="成员图任务关键词" value={query} onChange={event => setQuery(event.target.value)} placeholder="任务标题、编号或需求编号"/></div></label><GhostButton onClick={() => {setOwner('all'); setStatus(''); setSprint(''); setQuery('');}}>清空筛选</GhostButton></Card>
      <div className="metric-grid six"><Metric icon={icons.Database} label="计划期团队容量" value={`${Math.round(teamCapacity * 10) / 10}h`} sub={`${data.members.filter(member => member.active).length} 名有效成员`}/><Metric icon={icons.Clock} label="未完成工作量" value={`${Math.round(assignedHours * 10) / 10}h`} sub="剩余工时优先，否则估算减实际" tone="green"/><Metric icon={icons.TrendingUp} label="平均负荷率" value={averagePercent == null ? '未配置' : `${averagePercent.toFixed(1)}%`} sub="按当前计划跨度折算容量" tone="purple"/><Metric icon={icons.UsersRound} label="超载成员" value={overloaded} sub="负荷率超过 100%" tone={overloaded ? 'red' : 'green'}/><Metric icon={icons.FileText} label="未分配任务" value={data.unassigned.task_count} sub={`${data.unassigned.workload_hours}h 待协调`} tone={data.unassigned.task_count ? 'orange' : 'green'}/><Metric icon={icons.RefreshCcw} label="当前筛选" value={tasks.length} sub={`共享版本 v${data.plan.version}`}/></div>
      <Card className="s3-member-board"><SectionHead title="成员任务分组" right={<span className="muted">当前显示 {tasks.length} 项；已取消任务不占未来容量</span>}/>{groups.length ? <div className="s3-member-columns">{groups.map(group => <section className="s3-member-column" key={group.id}><header><Avatar name={group.name}/><span><b>{group.name}{group.active ? '' : '（已移除）'}</b><small>{group.role_name}</small></span>{group.load_percent != null ? <Tag tone={group.overloaded ? 'red' : 'blue'}>{group.load_percent.toFixed(1)}%</Tag> : <Tag tone="gray">未配置容量</Tag>}</header>{group.load_percent != null && <Progress value={Math.min(group.load_percent, 100)} tone={group.overloaded ? 'red' : 'blue'}/>}<p className="s3-member-load">未完成 {group.workload_hours}h{group.capacity_hours != null ? ` / 计划期容量 ${group.capacity_hours}h` : ''}</p><div className="s3-member-cards">{group.tasks.length ? group.tasks.map(task => <a key={task.id} href={`#kanban/${task.id}?project=${project.id}`}><div><b>{task.title}</b><Tag tone={tones[task.status]}>{task.status}</Tag></div><span>{task.id} · {task.requirement_id}</span><small>{task.planned_start && task.planned_end ? `${task.planned_start} 至 ${task.planned_end}` : '尚未完整排期'} · {taskHours(task)}h · v{task.version}</small>{task.dependencies.length > 0 && <em>前置 {task.dependencies.map(item => item.id).join('、')}</em>}</a>) : <Empty>当前筛选下无任务</Empty>}</div></section>)}</div> : <Empty>没有匹配的成员或任务。</Empty>}</Card>
      <Card className="s3-workload-card"><SectionHead title="工作负荷核对" right={<span className="muted">任务数量只用于回查，不作为绩效评分</span>}/><table><thead><tr><th>成员</th><th>有效状态</th><th>未完成任务</th><th>工作量</th><th>计划期容量</th><th>负荷率</th><th>技能标签</th></tr></thead><tbody>{data.members.map(member => <tr key={member.id}><td><Avatar name={member.name} size={24}/><b>{member.name}</b></td><td>{member.active ? <Tag tone="green">有效成员</Tag> : <Tag tone="gray">已移除历史</Tag>}</td><td>{member.task_count}</td><td>{member.workload_hours}h</td><td>{member.capacity_hours == null ? '未配置' : `${member.capacity_hours}h`}</td><td>{member.load_percent == null ? '无法计算' : <Tag tone={member.overloaded ? 'red' : 'blue'}>{member.load_percent.toFixed(1)}%</Tag>}</td><td>{member.skill_tags.length ? member.skill_tags.map(tag => <Tag key={tag} tone="purple">{tag}</Tag>) : '未配置'}</td></tr>)}</tbody></table></Card>
    </>}
  </>;
}
