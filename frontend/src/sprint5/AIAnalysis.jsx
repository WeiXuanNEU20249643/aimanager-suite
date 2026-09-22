import React, {useEffect, useRef, useState} from 'react';
import {Card, GhostButton, PageTitle, PrimaryButton, SectionHead, Tag, icons} from '../components';
import {projectApi} from '../api';
import {can, dateTime, useResource} from '../sprint1/shared';
import {Empty, ErrorNotice, Field, ResourceState} from '../sprint1/ui';

const statusLabels = {draft: '待审查', applied: '已应用', rejected: '已否决', failed: '调用失败'};
const statusTones = {draft: 'orange', applied: 'green', rejected: 'gray', failed: 'red'};
const capabilities = [
  ['prd_breakdown', 'AI需求拆解与估算', '提交有来源的 PRD，生成故事、验收条件、任务、依赖与工时草案', icons.ClipboardList],
  ['progress_forecast', '进度预测', '用实际与估算比中位数校准剩余工作，并解释预计完成日期', icons.TrendingUp],
  ['smart_schedule', '智能排期', '按优先级、依赖、技能、容量和可用期生成可确认的排期差异', icons.CalendarDays],
  ['risk_analysis', '风险预警', '按超载、阻塞、逾期和预测延期规则触发风险，并生成可执行应对建议', icons.AlertTriangle],
  ['quality_analysis', '质量分析', '核对选定代码、文档和测试报告，问题经人工确认后转为 S6 任务', icons.ShieldCheck],
  ['efficiency_analysis', '效率优化', '复算周期、等待、返工、阻塞和负荷差异，形成可比较的改进行动', icons.Target],
];

const initialArtifacts = [
  {artifact_type: 'code', label: '代码片段', file_name: '', version: '', content_scope: '', content: ''},
  {artifact_type: 'document', label: '需求或说明文档', file_name: '', version: '', content_scope: '', content: ''},
  {artifact_type: 'test_report', label: '测试报告', file_name: '', version: '', content_scope: '', content: ''},
];

export function AIAnalysis({project}) {
  const center = useResource(signal => projectApi(project.id, '/ai', {signal}), [project.id, project.role, project.role_id]);
  const [selectedId, setSelectedId] = useState(null);
  const [sourceName, setSourceName] = useState(''), [prdText, setPrdText] = useState('');
  const [asOfDate, setAsOfDate] = useState(''), [startDate, setStartDate] = useState('');
  const [riskDate, setRiskDate] = useState(''), [efficiencyDate, setEfficiencyDate] = useState('');
  const [overloadPercent, setOverloadPercent] = useState('100'), [blockedWorkdays, setBlockedWorkdays] = useState('1');
  const [thresholdReason, setThresholdReason] = useState('');
  const [qualityTarget, setQualityTarget] = useState(''), [qualityOwner, setQualityOwner] = useState('');
  const [qualityDueDate, setQualityDueDate] = useState(''), [artifacts, setArtifacts] = useState(initialArtifacts);
  const [busy, setBusy] = useState(''), [error, setError] = useState(null);
  const runs = center.data?.runs || [];
  useEffect(() => {
    if (!runs.length) setSelectedId(null);
    else if (!runs.some(item => item.id === selectedId)) setSelectedId(runs[0].id);
  }, [center.data, selectedId]);
  useEffect(() => {
    if (!center.data) return;
    setOverloadPercent(String(center.data.risk_thresholds.overload_percent));
    setBlockedWorkdays(String(center.data.risk_thresholds.blocked_workdays));
    setQualityTarget(value => value || center.data.quality_targets[0]?.id || '');
    setQualityOwner(value => value || String(center.data.members[0]?.id || ''));
  }, [center.data?.risk_thresholds?.version, project.id]);
  const selected = runs.find(item => item.id === selectedId) || null;
  const writable = can(project, 'ai.write');
  const qualityReady = qualityTarget && artifacts.every(item => item.file_name.trim() && item.version.trim() && item.content_scope.trim() && item.content.trim());

  async function generate(capability) {
    let path, body;
    if (capability === 'prd_breakdown') {
      if (!sourceName.trim() || !prdText.trim()) return;
      path = '/ai/prd-breakdowns'; body = {source_name: sourceName, prd_text: prdText};
    } else if (capability === 'progress_forecast') {
      path = '/ai/forecasts'; body = {as_of_date: asOfDate || null};
    } else if (capability === 'smart_schedule') {
      path = '/ai/schedules'; body = {start_date: startDate || null};
    } else if (capability === 'risk_analysis') {
      path = '/ai/risks'; body = {as_of_date: riskDate || null, overload_percent: Number(overloadPercent), blocked_workdays: Number(blockedWorkdays), threshold_reason: thresholdReason};
    } else if (capability === 'quality_analysis') {
      if (!qualityReady) return;
      path = '/ai/quality-analyses'; body = {target_requirement_id: qualityTarget, owner_id: qualityOwner ? Number(qualityOwner) : null, due_date: qualityDueDate || null, artifacts: artifacts.map(({label, ...item}) => item)};
    } else {
      path = '/ai/efficiency-analyses'; body = {as_of_date: efficiencyDate || null};
    }
    setBusy(capability); setError(null);
    try {
      const result = await projectApi(project.id, path, {method: 'POST', body});
      setSelectedId(result.id); center.reload();
    } catch (caught) {
      setError(caught); center.reload();
    } finally { setBusy(''); }
  }

  function updateArtifact(index, key, value) {
    setArtifacts(items => items.map((item, position) => position === index ? {...item, [key]: value} : item));
  }

  const generationReady = {
    prd_breakdown: Boolean(sourceName.trim() && prdText.trim()),
    progress_forecast: true,
    smart_schedule: true,
    risk_analysis: Number(overloadPercent) >= 1 && Number(blockedWorkdays) >= 0,
    quality_analysis: Boolean(qualityReady),
    efficiency_analysis: true,
  };

  return <>
    <PageTitle title={<span>AI 分析中心 <Tag tone="purple">Sprint 6</Tag></span>}
      subtitle="六项 AI 真实调用同一服务；风险、质量和效率结果先保留证据，再经人工审查形成任务或改进行动。"/>
    <ResourceState resource={center}>{center.data && <>
      <Card className={`s5-service ${center.data.service.configured ? 'ready' : 'missing'}`}>
        <div><icons.BrainCircuit size={22}/><span><b>{center.data.service.configured ? 'AI 服务已连接' : 'AI 服务尚未配置'}</b><small>{center.data.service.configured ? `${center.data.service.model_id} · 超时 ${center.data.service.timeout_seconds}s · 凭据仅在服务端使用` : '请在服务端配置 AIMANAGER_AI_ENDPOINT、AIMANAGER_AI_MODEL 和可选的 AIMANAGER_AI_API_KEY'}</small></span></div>
        <div><Tag tone={center.data.service.configured ? 'green' : 'orange'}>{center.data.service.configured ? '可真实调用' : '不可调用'}</Tag><span>数据版本 v{center.data.plan_version}</span></div>
      </Card>
      <ErrorNotice error={error} retry={center.reload}/>
      <div className="s5-feature-grid">{capabilities.map(([id, title, text, Icon]) => <Card className="s5-feature" key={id}>
        <div className={`s5-feature-icon ${id}`}><Icon size={22}/></div><div><b>{title}</b><p>{text}</p></div>
        {id === 'progress_forecast' && <input aria-label="预测基准日期" type="date" value={asOfDate} onChange={event => setAsOfDate(event.target.value)}/>}
        {id === 'smart_schedule' && <input aria-label="排期起始日期" type="date" value={startDate} onChange={event => setStartDate(event.target.value)}/>}
        {id === 'risk_analysis' && <div className="s6-risk-controls"><input aria-label="风险分析日期" type="date" value={riskDate} onChange={event => setRiskDate(event.target.value)}/><label>超载阈值 %<input aria-label="超载阈值" type="number" min="1" max="1000" value={overloadPercent} onChange={event => setOverloadPercent(event.target.value)}/></label><label>阻塞阈值 工作日<input aria-label="阻塞阈值" type="number" min="0" max="365" step="0.5" value={blockedWorkdays} onChange={event => setBlockedWorkdays(event.target.value)}/></label><input aria-label="阈值变更原因" value={thresholdReason} onChange={event => setThresholdReason(event.target.value)} maxLength={2000} placeholder="阈值变化时填写原因"/></div>}
        {id === 'quality_analysis' && <span className="s6-input-hint">请先在下方填写三类质量资料和承接需求。</span>}
        {id === 'efficiency_analysis' && <input aria-label="效率分析日期" type="date" value={efficiencyDate} onChange={event => setEfficiencyDate(event.target.value)}/>}
        <PrimaryButton icon={icons.Sparkles} disabled={!writable || busy || !center.data.service.configured || !generationReady[id]} onClick={() => generate(id)}>{busy === id ? '调用中…' : '生成草案'}</PrimaryButton>
      </Card>)}</div>
      <Card className="s5-prd-input"><SectionHead title="PRD 输入与来源" right={<span>失败时保留输入，但不会创建需求或任务</span>}/><div className="s5-prd-grid"><Field label="来源名称"><input value={sourceName} onChange={event => setSourceName(event.target.value)} maxLength={200} placeholder="例如 支付模块 PRD v1.2"/></Field><Field label="PRD 原文"><textarea value={prdText} onChange={event => setPrdText(event.target.value)} rows={6} maxLength={10000} placeholder="粘贴需要拆解的 PRD 原文；建议保留段落结构，便于核对来源。"/></Field></div><div className="s5-prd-action"><PrimaryButton icon={icons.Sparkles} disabled={!writable || busy || !center.data.service.configured || !sourceName.trim() || !prdText.trim()} onClick={() => generate('prd_breakdown')}>{busy === 'prd_breakdown' ? '正在调用 AI…' : '生成需求拆解草案'}</PrimaryButton></div></Card>
      <Card className="s6-quality-input"><SectionHead title="质量分析输入" right={<span>代码、文档、测试报告均至少一个可复现样例；AI 结论不替代实际运行测试</span>}/><div className="s6-quality-targets"><Field label="承接需求"><select aria-label="质量问题承接需求" value={qualityTarget} onChange={event => setQualityTarget(event.target.value)}><option value="">请选择需求</option>{center.data.quality_targets.map(item => <option value={item.id} key={item.id}>{item.id} · {item.title}</option>)}</select></Field><Field label="负责人"><select aria-label="质量任务负责人" value={qualityOwner} onChange={event => setQualityOwner(event.target.value)}><option value="">未分配</option>{center.data.members.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></Field><Field label="截止日"><input aria-label="质量任务截止日" type="date" value={qualityDueDate} onChange={event => setQualityDueDate(event.target.value)}/></Field></div><div className="s6-artifact-grid">{artifacts.map((item, index) => <article key={item.artifact_type}><b>{item.label}</b><div><input aria-label={`${item.label}文件名`} value={item.file_name} onChange={event => updateArtifact(index, 'file_name', event.target.value)} placeholder="文件名" maxLength={200}/><input aria-label={`${item.label}版本`} value={item.version} onChange={event => updateArtifact(index, 'version', event.target.value)} placeholder="版本或提交号" maxLength={200}/><input aria-label={`${item.label}内容范围`} value={item.content_scope} onChange={event => updateArtifact(index, 'content_scope', event.target.value)} placeholder="页码、行号或报告区段" maxLength={200}/></div><textarea aria-label={`${item.label}内容`} value={item.content} onChange={event => updateArtifact(index, 'content', event.target.value)} rows={6} maxLength={10000} placeholder="粘贴本次允许分析的内容"/></article>)}</div><div className="s5-prd-action"><PrimaryButton icon={icons.ShieldCheck} disabled={!writable || busy || !center.data.service.configured || !qualityReady} onClick={() => generate('quality_analysis')}>{busy === 'quality_analysis' ? '正在分析…' : '生成质量分析草案'}</PrimaryButton></div></Card>
      <div className="s5-review-layout"><Card className="s5-run-list"><SectionHead title="AI 调用与审查记录" right={<GhostButton onClick={center.reload}>刷新</GhostButton>}/>{runs.length ? runs.map(run => <button className={run.id === selectedId ? 'active' : ''} onClick={() => setSelectedId(run.id)} key={run.id}><span><b>#{run.id} {run.capability_label}</b><small>{dateTime(run.created_at)} · v{run.version}</small></span><Tag tone={statusTones[run.status]}>{statusLabels[run.status]}</Tag></button>) : <Empty>还没有 AI 调用记录。</Empty>}</Card>
        <RunReview key={selected?.id || 'none'} project={project} run={selected} onUpdated={run => {setSelectedId(run.id); center.reload();}}/>
      </div>
      <ActionList project={project} actions={center.data.actions} onUpdated={center.reload}/>
    </>}</ResourceState>
  </>;
}

function RunReview({project, run, onUpdated}) {
  const [output, setOutput] = useState(run?.output || null);
  const [reason, setReason] = useState(''), [error, setError] = useState(null), [busy, setBusy] = useState('');
  const operationIds = useRef({});
  useEffect(() => { setOutput(run?.output || null); setReason(''); setError(null); }, [run?.id, run?.version]);
  if (!run) return <Card className="s5-review"><Empty>选择一条记录查看输入、模型输出和审查结果。</Empty></Card>;
  const writable = can(project, 'ai.write'), applicable = can(project, 'ai.apply');
  async function saveEdit() {
    setBusy('edit'); setError(null);
    try { onUpdated(await projectApi(project.id, `/ai/runs/${run.id}`, {method: 'PATCH', body: {version: run.version, output, reason}})); }
    catch (caught) { setError(caught); } finally { setBusy(''); }
  }
  async function decide(action) {
    setBusy(action); setError(null);
    const body = {version: run.version, reason};
    if (action === 'apply') {
      operationIds.current[run.id] ||= crypto.randomUUID();
      body.operation_id = operationIds.current[run.id];
    }
    try { onUpdated(await projectApi(project.id, `/ai/runs/${run.id}/${action}`, {method: 'POST', body})); }
    catch (caught) { setError(caught); } finally { setBusy(''); }
  }
  const blockedSchedule = run.capability === 'smart_schedule' && output?.plan?.blocked;
  return <Card className="s5-review"><SectionHead title={`${run.capability_label} · #${run.id}`} right={<Tag tone={statusTones[run.status]}>{statusLabels[run.status]}</Tag>}/>
    <dl className="s5-run-meta"><dt>模型</dt><dd>{run.model_id || '未配置'}</dd><dt>输入版本</dt><dd>v{run.input_version}</dd><dt>调用人</dt><dd>{run.created_by_name}</dd><dt>调用时间</dt><dd>{dateTime(run.created_at)}</dd></dl>
    {run.status === 'failed' ? <div className="s5-failed"><icons.AlertTriangle size={20}/><div><b>{run.error_message}</b><span>错误代码 {run.error_code}。原始输入已记录，项目数据未变更。</span></div></div> : <OutputReview run={run} output={output} onChange={setOutput}/>}
    {run.reviews?.length > 0 && <div className="s5-review-history"><b>审查历史</b>{run.reviews.map(item => <p key={item.id}>{item.actor_name} · {item.action} · {item.reason} · {dateTime(item.created_at)}</p>)}</div>}
    {run.status === 'draft' && writable && <div className="s5-decision"><Field label="审查理由"><textarea value={reason} onChange={event => setReason(event.target.value)} rows={3} maxLength={10000} placeholder="说明修改、采纳或否决的依据"/></Field><ErrorNotice error={error}/><div>{run.capability === 'prd_breakdown' && <GhostButton disabled={busy || !reason.trim()} onClick={saveEdit}>{busy === 'edit' ? '保存中…' : '保存修改'}</GhostButton>}<button className="btn danger" disabled={busy || !reason.trim()} onClick={() => decide('reject')}>{busy === 'reject' ? '处理中…' : '否决'}</button>{applicable && <PrimaryButton icon={icons.Check} disabled={busy || !reason.trim() || blockedSchedule} onClick={() => decide('apply')}>{busy === 'apply' ? '应用中…' : blockedSchedule ? '先解决阻断冲突' : '确认并应用'}</PrimaryButton>}</div></div>}
  </Card>;
}

function OutputReview({run, output, onChange}) {
  if (run.capability === 'prd_breakdown') return <BreakdownReview output={output} editable={run.status === 'draft'} onChange={onChange}/>;
  if (run.capability === 'progress_forecast') return <ForecastReview output={output}/>;
  if (run.capability === 'risk_analysis') return <RiskReview output={output} members={run.input.members || []}/>;
  if (run.capability === 'quality_analysis') return <QualityReview output={output}/>;
  if (run.capability === 'efficiency_analysis') return <EfficiencyReview output={output}/>;
  return <ScheduleReview output={output}/>;
}

function BreakdownReview({output, editable, onChange}) {
  function updateStory(index, key, value) { onChange({...output, stories: output.stories.map((story, position) => position === index ? {...story, [key]: value} : story)}); }
  function updateTask(storyIndex, taskIndex, key, value) {
    onChange({...output, stories: output.stories.map((story, position) => position !== storyIndex ? story : {...story, tasks: story.tasks.map((task, taskPosition) => taskPosition === taskIndex ? {...task, [key]: value} : task)})});
  }
  return <div className="s5-breakdown"><div className="s5-output-summary"><Tag tone="green">{output.stories.length} 条有来源故事</Tag><Tag tone="orange">{output.ambiguous_items.length} 条歧义</Tag><Tag tone="gray">{output.unsupported_items.length} 条无来源建议</Tag></div>
    {output.stories.map((story, index) => <article key={story.local_id}><div className="s5-story-head"><b>{story.local_id}</b><select aria-label={`故事 ${index + 1} 优先级`} disabled={!editable} value={story.priority} onChange={event => updateStory(index, 'priority', event.target.value)}>{['Must','Should','Could',"Won't"].map(item => <option key={item}>{item}</option>)}</select></div><div className="s5-story-grid"><Field label={`故事 ${index + 1} 角色`}><input disabled={!editable} value={story.role} onChange={event => updateStory(index, 'role', event.target.value)}/></Field><Field label={`故事 ${index + 1} 标题`}><input disabled={!editable} value={story.story} onChange={event => updateStory(index, 'story', event.target.value)}/></Field><Field label={`故事 ${index + 1} 来源段落`}><textarea disabled={!editable} rows={2} value={story.source_paragraph} onChange={event => updateStory(index, 'source_paragraph', event.target.value)}/></Field><Field label={`故事 ${index + 1} 验收条件`}><textarea disabled={!editable} rows={3} value={story.acceptance_criteria.join('\n')} onChange={event => updateStory(index, 'acceptance_criteria', event.target.value.split('\n').map(value => value.trim()).filter(Boolean))}/></Field></div><div className="s5-draft-tasks">{story.tasks.map((task, taskIndex) => <div key={task.local_id}><b>{task.local_id}</b><input aria-label={`${task.local_id} 标题`} disabled={!editable} value={task.title} onChange={event => updateTask(index, taskIndex, 'title', event.target.value)}/><input aria-label={`${task.local_id} 工时`} disabled={!editable} type="number" min="0.25" step="0.25" value={task.estimate_hours} onChange={event => updateTask(index, taskIndex, 'estimate_hours', Number(event.target.value))}/><input aria-label={`${task.local_id} 技能`} disabled={!editable} value={task.required_skills.join('，')} onChange={event => updateTask(index, taskIndex, 'required_skills', event.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean))}/><input aria-label={`${task.local_id} 依赖`} disabled={!editable} value={task.depends_on.join('，')} onChange={event => updateTask(index, taskIndex, 'depends_on', event.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean))}/></div>)}</div></article>)}
    {output.ambiguous_items.length > 0 && <div className="s5-list"><b>歧义待确认</b>{output.ambiguous_items.map((item, index) => <p key={index}>{item}</p>)}</div>}
    {output.unsupported_items.length > 0 && <div className="s5-list"><b>无来源建议</b>{output.unsupported_items.map((item, index) => <p key={index}>{item.reason || JSON.stringify(item)}</p>)}</div>}
  </div>;
}

function ForecastReview({output}) {
  const evidence = output.evidence;
  return <div className="s5-forecast"><div className="s5-metrics"><div><span>预计完成日期</span><b>{evidence.expected_completion_date || '无法计算'}</b></div><div><span>有效历史样本</span><b>{evidence.sample_count}</b></div><div><span>实际/估算中位数</span><b>{evidence.median_actual_estimate_ratio}</b></div></div>{evidence.data_notice && <p className="s5-notice">{evidence.data_notice}</p>}<h4>AI 解释</h4><p>{output.explanation.summary}</p><ul>{output.explanation.factors.map(item => <li key={item}>{item}</li>)}</ul><h4>计算过程</h4><p>{evidence.calculation}</p><div className="s5-table-scroll"><table><thead><tr><th>任务</th><th>估算</th><th>实际</th><th>比值</th></tr></thead><tbody>{evidence.samples.map(item => <tr key={item.task_id}><td>{item.task_id} · {item.title}</td><td>{item.estimated_hours}h</td><td>{item.actual_hours}h</td><td>{item.ratio}</td></tr>)}</tbody></table></div><ConflictList conflicts={evidence.conflicts}/></div>;
}

function ScheduleReview({output}) {
  const plan = output.plan;
  const explanations = Object.fromEntries(output.explanation.assignments.map(item => [item.task_id, item]));
  return <div className="s5-schedule"><div className="s5-output-summary"><Tag tone={plan.blocked ? 'red' : 'green'}>{plan.blocked ? '存在阻断冲突' : '约束检查通过'}</Tag><Tag>{plan.proposals.length} 项变更</Tag><Tag tone="gray">{plan.preserved.length} 项保留</Tag></div><p>{output.explanation.summary}</p><div className="s5-table-scroll"><table><thead><tr><th>任务</th><th>优先级</th><th>负责人变化</th><th>日期变化</th><th>理由与取舍</th></tr></thead><tbody>{plan.proposals.map(item => <tr key={item.task_id}><td><b>{item.task_id}</b><span>{item.title}</span></td><td>{item.priority}</td><td>{item.before_owner_name || '未分配'} → {item.after_owner_name}</td><td>{item.before_start || '未排期'} 至 {item.before_end || '未排期'}<br/>→ {item.after_start} 至 {item.after_end}</td><td>{explanations[item.task_id]?.reason}<small>{explanations[item.task_id]?.tradeoffs.join('；')}</small></td></tr>)}</tbody></table></div><ConflictList conflicts={plan.conflicts}/><div className="s5-preserved"><b>不移动的任务</b>{plan.preserved.map(item => <span key={item.task_id}>{item.task_id} · {item.reason}</span>)}</div></div>;
}

function RiskReview({output, members}) {
  const advice = Object.fromEntries(output.analysis.risks.map(item => [item.risk_id, item]));
  const memberNames = Object.fromEntries(members.map(item => [item.id, item.name]));
  const tones = {high: 'red', medium: 'orange', low: 'blue'};
  const labels = {high: '高风险', medium: '中风险', low: '低风险'};
  return <div className="s6-analysis"><div className="s5-output-summary"><Tag tone={output.evidence.risks.length ? 'red' : 'green'}>{output.evidence.risks.length} 项触发风险</Tag><Tag tone="orange">{output.evidence.missing_data.length} 项缺失数据</Tag><Tag tone="gray">阈值 v{output.evidence.thresholds.version}</Tag></div><p>{output.analysis.summary}</p><div className="s5-table-scroll"><table><thead><tr><th>风险与级别</th><th>影响任务</th><th>证据</th><th>应对建议</th><th>负责人 / 复查</th></tr></thead><tbody>{output.evidence.risks.map(item => <tr key={item.risk_id}><td><b>{item.title}</b><Tag tone={tones[advice[item.risk_id]?.severity]}>{labels[advice[item.risk_id]?.severity]}</Tag></td><td>{item.task_ids.join('、')}</td><td>{item.evidence}</td><td>{advice[item.risk_id]?.recommendation}</td><td>{memberNames[advice[item.risk_id]?.owner_id] || `成员 #${advice[item.risk_id]?.owner_id}`}<small>{advice[item.risk_id]?.next_check_date}</small></td></tr>)}</tbody></table></div>{output.evidence.missing_data.length > 0 && <div className="s5-conflicts"><b>缺失数据</b>{output.evidence.missing_data.map((item, index) => <p key={`${item.task_id || item.owner_id}-${item.field}-${index}`}>{item.task_id || memberNames[item.owner_id] || `成员 #${item.owner_id}`} · {item.message}</p>)}</div>}</div>;
}

function QualityReview({output}) {
  return <div className="s6-analysis"><div className="s5-output-summary"><Tag tone={output.analysis.issues.length ? 'orange' : 'green'}>{output.analysis.issues.length} 项待核实问题</Tag><Tag tone="gray">静态分析不等同运行测试</Tag></div><p>{output.analysis.summary}</p><div className="s5-table-scroll"><table><thead><tr><th>问题</th><th>来源位置</th><th>可定位依据</th><th>影响与建议</th><th>转为</th></tr></thead><tbody>{output.analysis.issues.map(item => <tr key={item.issue_id}><td><b>{item.title}</b><span>{item.category}</span></td><td>{item.file_name}<small>{item.location}</small></td><td>{item.evidence}</td><td>{item.impact}<small>{item.recommendation}</small></td><td><Tag tone={item.task_kind === 'defect' ? 'red' : 'blue'}>{item.task_kind === 'defect' ? '缺陷任务' : '改进任务'}</Tag></td></tr>)}</tbody></table></div></div>;
}

function EfficiencyReview({output}) {
  const advice = Object.fromEntries(output.analysis.bottlenecks.map(item => [item.metric_key, item]));
  return <div className="s6-analysis"><div className="s5-metrics">{output.evidence.metrics.map(item => <div key={item.key}><span>{item.label}</span><b>{item.value} {item.unit}</b><small>{item.sample_count} 条记录</small></div>)}</div>{output.evidence.data_notice && <p className="s5-notice">{output.evidence.data_notice}</p>}<p>{output.analysis.summary}</p><p className="s6-rule">{output.evidence.interpretation_rule}</p>{output.analysis.bottlenecks.length > 0 && <div className="s5-table-scroll"><table><thead><tr><th>指标</th><th>瓶颈依据</th><th>建议</th><th>行动与复核</th></tr></thead><tbody>{output.evidence.metrics.filter(item => advice[item.key]).map(item => <tr key={item.key}><td><b>{item.label}</b><span>{item.value} {item.unit}</span></td><td>{advice[item.key].bottleneck}</td><td>{advice[item.key].recommendation}</td><td>{advice[item.key].action_title}<small>{advice[item.key].review_metric} · {advice[item.key].due_date}</small></td></tr>)}</tbody></table></div>}<div className="s5-preserved"><b>参与计算的任务记录与覆盖期</b><span>{output.evidence.coverage_start || '暂无'} 至 {output.evidence.coverage_end} · {output.evidence.task_records.length} 条任务记录</span></div></div>;
}

function ActionList({project, actions, onUpdated}) {
  return <Card className="s6-actions"><SectionHead title="风险与效率改进行动" right={<span>只有复核指标优于创建时基线，才允许人工关闭</span>}/>{actions.length ? <div className="s6-action-list">{actions.map(action => <ActionRow project={project} action={action} onUpdated={onUpdated} key={action.id}/>)}</div> : <Empty>采纳风险或效率建议后，行动会在这里持续跟踪。</Empty>}</Card>;
}

function ActionRow({project, action, onUpdated}) {
  const [busy, setBusy] = useState(''), [error, setError] = useState(null);
  const metricRef = useRef(null), noteRef = useRef(null);
  async function update(status) {
    setBusy(status); setError(null);
    const metric = metricRef.current?.value ?? '';
    const note = noteRef.current?.value ?? '';
    try {
      await projectApi(project.id, `/ai/actions/${action.id}`, {method: 'PATCH', body: {status, version: action.version, current_metric_value: metric === '' ? null : Number(metric), review_note: note}});
      onUpdated();
    } catch (caught) { setError(caught); } finally { setBusy(''); }
  }
  return <article><div className="s6-action-head"><span><Tag tone={action.source_kind === 'risk' ? 'red' : 'purple'}>{action.source_kind === 'risk' ? '风险行动' : '效率行动'}</Tag><b>{action.title}</b></span><Tag tone={action.status === '已完成' ? 'green' : action.status === '进行中' ? 'blue' : 'orange'}>{action.status}</Tag></div><p>{action.description}</p><div className="s6-action-meta"><span>负责人 {action.owner_name}</span><span>期限 {action.due_date}</span><span>基线 {action.baseline_metric_value}</span><span>{action.review_metric}</span></div>{action.status !== '已完成' && can(project, 'ai.apply') && <><div className="s6-action-review"><input ref={metricRef} aria-label={`行动 ${action.id} 当前指标`} type="text" inputMode="decimal" defaultValue={action.current_metric_value ?? ''} placeholder="当前指标"/><input ref={noteRef} aria-label={`行动 ${action.id} 复核说明`} defaultValue={action.review_note || ''} maxLength={10000} placeholder="人工复核说明"/>{action.status === '待处理' && <GhostButton disabled={busy} onClick={() => update('进行中')}>开始行动</GhostButton>}<PrimaryButton icon={icons.Check} disabled={busy} onClick={() => update('已完成')}>复核并关闭</PrimaryButton></div><ErrorNotice error={error}/></>}</article>;
}

function ConflictList({conflicts}) {
  if (!conflicts.length) return <div className="s5-ok"><icons.Check size={16}/>未发现约束冲突</div>;
  return <div className="s5-conflicts"><b>约束与冲突</b>{conflicts.map((item, index) => <p key={`${item.task_id || 'project'}-${item.type}-${index}`}><Tag tone={item.severity === 'error' ? 'red' : 'orange'}>{item.severity === 'error' ? '阻断' : '提醒'}</Tag>{item.task_id ? `${item.task_id} · ` : ''}{item.message}</p>)}</div>;
}
