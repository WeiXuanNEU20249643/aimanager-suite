import React from 'react';
import {PageTitle, Card, GhostButton, Metric, SectionHead, Tag, icons} from '../components';
import {ownerLabel, tones} from '../sprint1/shared';
import {Empty, ErrorNotice, Loading} from '../sprint1/ui';
import {dateOffset, taskHours, usePlanningData} from './shared';

export function Gantt({project}) {
  const resource = usePlanningData(project.id);
  const data = resource.data;
  const scheduled = data?.tasks.filter(task => task.planned_start && task.planned_end)
    .sort((a, b) => a.planned_start.localeCompare(b.planned_start) || a.id.localeCompare(b.id)) || [];
  const unscheduled = data?.tasks.filter(task => !task.planned_start || !task.planned_end) || [];
  const horizon = data?.horizon;
  const totalDays = Math.max(horizon?.days || 1, 1);
  const totalHours = data?.tasks.reduce((sum, task) => sum + Number(task.estimated_hours || 0), 0) || 0;
  const dependencyCount = data?.tasks.reduce((sum, task) => sum + task.dependencies.length, 0) || 0;
  return <>
    <PageTitle title="甘特图 / 计划联动" subtitle="读取任务的真实计划日期、负责人和依赖；不维护独立排期副本。" actions={<><Card className="period"><icons.CalendarDays size={18}/><div><small>当前排期范围</small><b>{horizon?.start && horizon?.end ? `${horizon.start} - ${horizon.end}` : '尚未形成计划范围'}</b></div></Card><GhostButton icon={icons.RefreshCcw} onClick={resource.reload}>刷新排期</GhostButton></>}/>
    <div className="tabs"><a className="active" href={`#gantt?project=${project.id}`}>甘特图</a><a href={`#members?project=${project.id}`}>成员任务图</a></div>
    {resource.error && <ErrorNotice error={resource.error} retry={resource.reload}/>} 
    {resource.loading && !data ? <Loading/> : data && <>
      <div className="s3-version-strip"><span>共享排期版本 <b>v{data.plan.version}</b></span><span>{data.plan.updated_at ? `最近更新 ${new Date(data.plan.updated_at).toLocaleString('zh-CN', {hour12:false})} · ${data.plan.updated_by_name}` : '尚无排期变更记录'}</span><span>已取消任务 {data.cancelled_count} 项，默认不进入图表</span></div>
      <div className="metric-grid five"><Metric icon={icons.Database} label="有效任务" value={data.tasks.length} sub="与看板使用相同任务 ID"/><Metric icon={icons.CalendarDays} label="已排期" value={scheduled.length} sub="同时具备开始与结束日期" tone="green"/><Metric icon={icons.Hourglass} label="未排期" value={unscheduled.length} sub="缺失日期时单独列示" tone={unscheduled.length ? 'orange' : 'green'}/><Metric icon={icons.Clock} label="总估算工时" value={`${totalHours}h`} sub="来自任务估算字段" tone="purple"/><Metric icon={icons.GitBranch} label="依赖关系" value={dependencyCount} sub="仅统计当前项目"/></div>
      <Card className="s3-gantt-card"><SectionHead title="任务计划" right={<span className="muted">点击甘特条进入同一任务详情</span>}/>{scheduled.length && horizon?.start ? <div className="s3-gantt-grid">
        <div className="s3-gantt-axis"><span>任务 / 负责人 / 日期 / 工时</span><div><b>{horizon.start}</b><span>共享时间轴 · {totalDays} 天</span><b>{horizon.end}</b></div></div>
        {scheduled.map(task => { const left = Math.max(0, dateOffset(task.planned_start, horizon.start) / totalDays * 100); const days = dateOffset(task.planned_end, task.planned_start) + 1; const width = Math.min(100 - left, Math.max(days / totalDays * 100, 2)); return <div className="s3-gantt-row" key={task.id}><div className="s3-gantt-info"><span><a href={`#kanban/${task.id}?project=${project.id}`}>{task.id} · {task.title}</a><small>{ownerLabel(task)} · {task.planned_start} 至 {task.planned_end} · {taskHours(task)}h</small></span><div><Tag tone={tones[task.status]}>{task.status}</Tag>{task.plan_locked && <Tag tone="purple">已锁定</Tag>}</div>{task.dependencies.length > 0 && <small className="s3-dependencies">前置：{task.dependencies.map(item => item.id).join('、')}</small>}</div><div className="s3-gantt-track"><a aria-label={`${task.id} ${task.title}`} href={`#kanban/${task.id}?project=${project.id}`} className={`s3-gantt-bar ${task.plan_locked ? 'locked' : ''}`} style={{left: `${left}%`, width: `${width}%`}}><span>{task.title}</span></a></div></div>;})}
      </div> : <Empty>当前项目没有已排期任务。请先在任务详情维护计划日期，或从需求影响清单确认自动重排。</Empty>}</Card>
      <div className="s3-bottom-grid"><Card><SectionHead title={`未排期任务 · ${unscheduled.length}`}/>{unscheduled.length ? <div className="s3-unscheduled-list">{unscheduled.map(task => <a key={task.id} href={`#kanban/${task.id}?project=${project.id}`}><span><b>{task.id} · {task.title}</b><small>{ownerLabel(task)} · {task.status}</small></span><Tag tone="orange">缺失{!task.planned_start && !task.planned_end ? '开始及结束日期' : !task.planned_start ? '开始日期' : '结束日期'}</Tag></a>)}</div> : <Empty>所有有效任务均已有完整计划日期。</Empty>}</Card><Card><SectionHead title="数据边界"/><div className="s3-rule-list"><p><b>同源数据</b><span>甘特图、成员任务图与看板共享任务 ID、版本、状态、负责人和取消标记。</span></p><p><b>日期边界</b><span>时间轴按当前项目最早开始至最晚结束计算，跨月日期不会另存副本。</span></p><p><b>取消处理</b><span>已取消任务保留历史，但不进入当前甘特图及未来容量。</span></p></div></Card></div>
    </>}
  </>;
}
