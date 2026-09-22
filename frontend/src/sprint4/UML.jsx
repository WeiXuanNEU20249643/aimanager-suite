import React, {useEffect, useMemo, useState} from 'react';
import {Card, GhostButton, PageTitle, PrimaryButton, SectionHead, Tag, icons} from '../components';
import {projectApi} from '../api';
import {can, dateTime, useResource} from '../sprint1/shared';
import {Empty, ErrorNotice, Field, Modal, ResourceState} from '../sprint1/ui';

export function UML({project}) {
  const [tab, setTab] = useState('use_case');
  const [selectedId, setSelectedId] = useState(null);
  const [editor, setEditor] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const center = useResource(signal => projectApi(project.id, '/uml', {signal}), [project.id, project.role, project.role_id]);
  const scenarios = center.data?.scenarios || [];
  useEffect(() => {
    if (!scenarios.length) setSelectedId(null);
    else if (!scenarios.some(item => item.id === selectedId)) setSelectedId(scenarios[0].id);
  }, [center.data, selectedId]);
  const selected = scenarios.find(item => item.id === selectedId) || null;
  const writable = can(project, 'uml.write');

  async function generateUseCase() {
    setBusy(true); setError(null);
    try {
      await projectApi(project.id, '/uml/use-case/generate', {method: 'POST', body: {source_version: center.data.source_version}});
      center.reload();
    } catch (caught) { setError(caught); }
    finally { setBusy(false); }
  }

  async function generateSequence() {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      await projectApi(project.id, `/uml/scenarios/${selected.id}/generate`, {method: 'POST', body: {scenario_version: selected.version}});
      center.reload();
    } catch (caught) { setError(caught); }
    finally { setBusy(false); }
  }

  return <>
    <PageTitle title="UML中心" subtitle="从当前项目的故事角色、需求、任务和显式交互步骤生成可追溯图示。"/>
    <div className="tabs s4-tabs" role="tablist">
      <button role="tab" aria-selected={tab === 'use_case'} className={tab === 'use_case' ? 'active' : ''} onClick={() => setTab('use_case')}>用例图</button>
      <button role="tab" aria-selected={tab === 'sequence'} className={tab === 'sequence' ? 'active' : ''} onClick={() => setTab('sequence')}>时序图</button>
    </div>
    <ErrorNotice error={error} retry={center.reload}/>
    <ResourceState resource={center}>{center.data && (tab === 'use_case'
      ? <UseCasePanel project={project} generation={center.data.use_case} stale={center.data.use_case_stale}
          sourceVersion={center.data.source_version} writable={writable} busy={busy} onGenerate={generateUseCase}/>
      : <SequencePanel project={project} scenarios={scenarios} selected={selected} selectedId={selectedId}
          onSelect={value => setSelectedId(Number(value))} writable={writable} busy={busy}
          onCreate={() => setEditor({})} onEdit={() => setEditor(selected)} onGenerate={generateSequence}/>)}</ResourceState>
    {editor && <ScenarioForm project={project} scenario={editor.id ? editor : null} onClose={() => setEditor(null)}
      onSaved={saved => {setEditor(null); setSelectedId(saved.id); center.reload();}}/>}
  </>;
}

function UseCasePanel({project, generation, stale, sourceVersion, writable, busy, onGenerate}) {
  const content = generation?.content;
  return <>
    <Card className="s4-toolbar"><div><b>项目用例覆盖</b><span>来源版本 v{sourceVersion} · 仅使用已保存的故事角色与关联任务</span></div>
      {writable && <PrimaryButton icon={icons.RefreshCcw} disabled={busy} onClick={onGenerate}>{busy ? '生成中…' : generation ? '重新生成用例图' : '生成用例图'}</PrimaryButton>}</Card>
    {!generation ? <Card><Empty>{writable ? '尚未生成用例图。请先在需求中确认故事角色并建立关联任务。' : '尚未生成用例图，请联系有 UML 写权限的成员。'}</Empty></Card>
      : <div className="s4-uml-layout">
        <Card className="s4-diagram-card"><SectionHead title={`${content.project_name} 用例图`} right={<div className="s4-title-tags"><Tag tone={stale ? 'orange' : 'green'}>{stale ? '来源已变化' : '来源一致'}</Tag><Tag>图版本 v{generation.version}</Tag></div>}/>
          <div className="s4-usecase" aria-label="项目用例图">
            {content.actors.map(actor => <section className="s4-actor-group" key={actor.id}>
              <div className="s4-actor"><span className="s4-actor-head"/><span className="s4-actor-body"/><b>{actor.name}</b></div>
              <div className="s4-case-list">{content.use_cases.filter(item => item.actor === actor.name).map(item => <UseCase key={item.id} project={project} item={item}/>)}</div>
            </section>)}
            {content.use_cases.some(item => !item.actor) && <section className="s4-actor-group unlinked"><div className="s4-actor pending"><icons.AlertTriangle size={24}/><b>角色待确认</b></div><div className="s4-case-list">{content.use_cases.filter(item => !item.actor).map(item => <UseCase key={item.id} project={project} item={item}/>)}</div></section>}
          </div>
        </Card>
        <Card className="s4-meta"><SectionHead title="生成信息"/>
          <dl className="meta-list"><dt>覆盖结果</dt><dd><Tag tone={content.coverage.passed ? 'green' : 'orange'}>{content.coverage.covered_count}/{content.coverage.source_count} 个场景完整</Tag></dd><dt>最少核心场景</dt><dd>{content.coverage.minimum_core_scenarios}</dd><dt>来源版本</dt><dd>v{generation.source_version}</dd><dt>生成时间</dt><dd>{dateTime(generation.generated_at)}</dd><dt>操作者</dt><dd>{generation.generated_by_name}</dd></dl>
          <Warnings warnings={generation.warnings} project={project}/>
        </Card>
      </div>}
  </>;
}

function UseCase({project, item}) {
  return <article className="s4-case"><div><a href={`#requirements/${item.id}?project=${project.id}`}>{item.id}</a><span>v{item.requirement_version}</span></div><b>{item.name}</b>
    <div className="s4-case-tasks">{item.tasks.length ? item.tasks.map(task => <a className={task.cancelled ? 'cancelled' : ''} key={task.id} href={`#kanban/${task.id}?project=${project.id}`}>{task.id} · {task.status}{task.cancelled ? ' · 已取消' : ''}</a>) : <span>无关联任务</span>}</div></article>;
}

function Warnings({warnings, project}) {
  if (!warnings.length) return <div className="s4-ok">未发现来源缺项或重复关系</div>;
  return <div className="s4-warnings"><b>可定位提示 · {warnings.length}</b>{warnings.map((warning, index) => <div key={`${warning.code}-${warning.source_id}-${index}`}><icons.AlertTriangle size={15}/><span>{warning.source_id ? <a href={`#requirements/${warning.source_id}?project=${project.id}`}>{warning.source_id}</a> : null} {warning.message}</span></div>)}</div>;
}

function SequencePanel({project, scenarios, selected, selectedId, onSelect, writable, busy, onCreate, onEdit, onGenerate}) {
  const generation = selected?.latest_generation;
  return <>
    <Card className="s4-toolbar"><label>业务场景<select aria-label="业务场景" value={selectedId || ''} onChange={event => onSelect(event.target.value)}><option value="" disabled>{scenarios.length ? '选择场景' : '暂无场景'}</option>{scenarios.map(item => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></label>
      <div>{writable && <><GhostButton onClick={onCreate}>新建场景</GhostButton>{selected && <GhostButton onClick={onEdit}>编辑场景</GhostButton>}<PrimaryButton icon={icons.RefreshCcw} disabled={!selected || busy} onClick={onGenerate}>{busy ? '生成中…' : generation ? '重新生成时序图' : '生成时序图'}</PrimaryButton></>}</div></Card>
    {!selected ? <Card><Empty>{writable ? '创建业务场景，按顺序保存参与者、消息、条件分支和来源任务。' : '暂无可查看的时序场景。'}</Empty></Card>
      : !generation ? <Card><Empty>场景“{selected.name}”尚未生成时序图。已保存 {selected.participants.length} 个参与者和 {selected.messages.length} 条消息。</Empty></Card>
      : <div className="s4-uml-layout"><Card className="s4-diagram-card"><SectionHead title={`${generation.content.name} 时序图`} right={<div className="s4-title-tags"><Tag tone={selected.generation_stale ? 'orange' : 'green'}>{selected.generation_stale ? '场景已变化' : '来源一致'}</Tag><Tag>图版本 v{generation.version}</Tag></div>}/><SequenceDiagram project={project} content={generation.content}/></Card>
        <Card className="s4-meta"><SectionHead title="场景信息"/><p className="long-text">{generation.content.description || '未填写场景说明'}</p><dl className="meta-list"><dt>场景版本</dt><dd>v{generation.source_version}</dd><dt>参与者</dt><dd>{generation.content.participants.length} 个</dd><dt>消息</dt><dd>{generation.content.messages.length} 条</dd><dt>关联需求</dt><dd>{generation.content.requirement_ids.map(id => <a key={id} href={`#requirements/${id}?project=${project.id}`}>{id} </a>)}</dd><dt>生成时间</dt><dd>{dateTime(generation.generated_at)}</dd><dt>操作者</dt><dd>{generation.generated_by_name}</dd></dl></Card></div>}
  </>;
}

function SequenceDiagram({project, content}) {
  const count = content.participants.length;
  const height = 82 + content.messages.length * 76;
  return <div className="s4-sequence" style={{height}} aria-label={`${content.name} 时序图`}>
    <div className="s4-participants" style={{gridTemplateColumns: `repeat(${count}, minmax(110px, 1fr))`}}>{content.participants.map(name => <div key={name}>{name}</div>)}</div>
    <div className="s4-lifelines" style={{gridTemplateColumns: `repeat(${count}, minmax(110px, 1fr))`}}>{content.participants.map(name => <i key={name}/>)}</div>
    {content.messages.map((message, index) => {
      const from = (message.from_index + .5) * 100 / count, to = (message.to_index + .5) * 100 / count;
      const self = message.from_index === message.to_index;
      const left = self ? Math.max(0, from - 1) : Math.min(from, to);
      const width = self ? Math.min(5, 100 - left) : Math.abs(to - from);
      return <div className={`s4-sequence-message ${message.to_index < message.from_index ? 'reverse' : ''}`} style={{top: 68 + index * 76}} key={`${message.order}-${message.task_id}`}>
        {message.branch_condition && <span className="s4-branch">条件 {message.branch_condition}</span>}
        <span className="s4-message-label" style={{left: `${left + width / 2}%`}}>{message.order}. {message.label} <a href={`#kanban/${message.task_id}?project=${project.id}`}>{message.task_id}</a>{message.cancelled ? ' · 已取消' : ''}</span>
        <span className="s4-message-line" style={{left: `${left}%`, width: `${width}%`}}/>
      </div>;
    })}
  </div>;
}

function ScenarioForm({project, scenario, onClose, onSaved}) {
  const [name, setName] = useState(scenario?.name || '');
  const [description, setDescription] = useState(scenario?.description || '');
  const [participants, setParticipants] = useState(scenario?.participants || ['发起人', '系统']);
  const [messages, setMessages] = useState(scenario?.messages || [{from_participant: '发起人', to_participant: '系统', label: '', branch_condition: '', task_id: ''}]);
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  const participantOptions = useMemo(() => participants.filter(Boolean), [participants]);
  function updateParticipant(index, value) {setParticipants(items => items.map((item, position) => position === index ? value : item));}
  function updateMessage(index, key, value) {setMessages(items => items.map((item, position) => position === index ? {...item, [key]: value} : item));}
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const body = {name, description, participants, messages: messages.map(item => ({...item, task_id: item.task_id || null}))};
    if (scenario) body.version = scenario.version;
    try {onSaved(await projectApi(project.id, '/uml/scenarios' + (scenario ? `/${scenario.id}` : ''), {method: scenario ? 'PATCH' : 'POST', body}));}
    catch (caught) {setError(caught);} finally {setBusy(false);}
  }
  return <Modal title={scenario ? `编辑时序场景 · ${scenario.name}` : '新建时序场景'} onClose={onClose}><form onSubmit={submit} className="s4-scenario-form">
    <Field label="场景名称"><input value={name} onChange={event => setName(event.target.value)} required maxLength={200}/></Field>
    <Field label="场景说明"><textarea value={description} onChange={event => setDescription(event.target.value)} rows={3} maxLength={2000}/></Field>
    <div className="s4-form-head"><b>参与者</b><GhostButton type="button" onClick={() => setParticipants(items => [...items, ''])}>添加参与者</GhostButton></div>
    {participants.map((participant, index) => <div className="s4-participant-row" key={index}><input aria-label={`参与者 ${index + 1}`} value={participant} onChange={event => updateParticipant(index, event.target.value)} required maxLength={200}/><button type="button" disabled={participants.length <= 2} onClick={() => setParticipants(items => items.filter((_, position) => position !== index))}>移除</button></div>)}
    <div className="s4-form-head"><b>消息顺序</b><GhostButton type="button" onClick={() => setMessages(items => [...items, {from_participant: participantOptions[0] || '', to_participant: participantOptions[1] || participantOptions[0] || '', label: '', branch_condition: '', task_id: ''}])}>添加消息</GhostButton></div>
    {messages.map((message, index) => <div className="s4-message-editor" key={index}><b>第 {index + 1} 条</b><select aria-label={`第 ${index + 1} 条发送方`} value={message.from_participant} onChange={event => updateMessage(index, 'from_participant', event.target.value)}>{participantOptions.map(item => <option key={item}>{item}</option>)}</select><span>→</span><select aria-label={`第 ${index + 1} 条接收方`} value={message.to_participant} onChange={event => updateMessage(index, 'to_participant', event.target.value)}>{participantOptions.map(item => <option key={item}>{item}</option>)}</select><input aria-label={`第 ${index + 1} 条消息`} value={message.label} onChange={event => updateMessage(index, 'label', event.target.value)} placeholder="消息内容" required maxLength={200}/><input aria-label={`第 ${index + 1} 条条件分支`} value={message.branch_condition || ''} onChange={event => updateMessage(index, 'branch_condition', event.target.value)} placeholder="条件分支（可选）" maxLength={200}/><input aria-label={`第 ${index + 1} 条来源任务`} value={message.task_id || ''} onChange={event => updateMessage(index, 'task_id', event.target.value)} placeholder="来源任务，例如 T-001" required maxLength={32}/><button type="button" disabled={messages.length <= 1} onClick={() => setMessages(items => items.filter((_, position) => position !== index))}>移除</button></div>)}
    <ErrorNotice error={error}/><div className="editor-actions"><GhostButton type="button" onClick={onClose}>取消</GhostButton><PrimaryButton icon={null} disabled={busy}>{busy ? '保存中…' : scenario ? '保存新版本' : '保存场景'}</PrimaryButton></div>
  </form></Modal>;
}
