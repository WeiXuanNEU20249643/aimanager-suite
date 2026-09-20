import React, {useState} from 'react';
import {Avatar, PageTitle, Card, SectionHead, PrimaryButton, GhostButton, Tag} from '../components';
import {projectApi} from '../api';
import {useResource} from './shared';
import {Empty, ErrorNotice, Field, Modal, ResourceState} from './ui';

const permissionLabels = {
  'requirement.read': '查看需求', 'requirement.write': '维护需求', 'requirement.history': '查看需求版本',
  'task.read': '查看任务', 'task.write': '维护任务', 'comment.read': '查看评论', 'comment.write': '发表评论',
  'milestone.read': '查看里程碑', 'milestone.write': '维护里程碑', 'statistics.read': '查看统计', 'history.read': '查看历史',
};
const modules = {requirement: '需求', task: '任务', comment: '评论', milestone: '里程碑', statistics: '统计', history: '历史'};

export function Permissions({project, onMembershipChange}) {
  const resource = useResource(async signal => {
    const [members, roles, catalog] = await Promise.all(['/members', '/roles', '/roles/permissions'].map(path => projectApi(project.id, path, {signal})));
    return {members, roles, catalog};
  }, [project.id, project.role, project.role_id]);
  const [memberEditor, setMemberEditor] = useState(null), [roleEditor, setRoleEditor] = useState(null), [removing, setRemoving] = useState(null);
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  const admin = project.role === 'admin';
  async function remove() {
    setBusy(true); setError(null);
    try { await projectApi(project.id, '/members/' + removing.id, {method: 'DELETE'}); setRemoving(null); resource.reload(); onMembershipChange(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  const data = resource.data || {members: [], roles: [], catalog: []};
  return <>
    <PageTitle title="成员与权限" subtitle="内置角色保持安全边界，自定义角色按项目配置并在下一次请求即时生效。" actions={<>{admin && <><PrimaryButton onClick={() => setMemberEditor({})}>添加成员</PrimaryButton><GhostButton onClick={() => setRoleEditor({})}>新建自定义角色</GhostButton></>}<GhostButton onClick={resource.reload}>刷新</GhostButton></>}/>
    <ResourceState resource={resource}><>
      <Card><SectionHead title={`项目成员 · ${data.members.length} 位`}/>{data.members.length ? <table className="member-table"><thead><tr><th>成员</th><th>账号</th><th>当前角色</th><th>类型</th>{admin && <th>操作</th>}</tr></thead><tbody>{data.members.map(member => <tr key={member.id}><td><Avatar name={member.name}/><b>{member.name}</b></td><td>{member.username}</td><td><Tag tone={member.role === 'admin' ? 'red' : member.role === 'observer' ? 'green' : member.custom_role_id ? 'purple' : 'blue'}>{member.role_name}</Tag></td><td>{member.custom_role_id ? '项目自定义' : '内置角色'}</td>{admin && <td><GhostButton onClick={() => setMemberEditor(member)}>分配角色</GhostButton> <GhostButton onClick={() => {setError(null); setRemoving(member);}}>移除</GhostButton></td>}</tr>)}</tbody></table> : <Empty>暂无成员</Empty>}</Card>
      <div className="s2-role-layout"><Card><SectionHead title="项目角色" right={admin && <GhostButton onClick={() => setRoleEditor({})}>新建角色</GhostButton>}/><div className="role-list">{data.roles.map(role => <button key={role.key} className="role-card" onClick={() => !role.builtin && admin && setRoleEditor(role)} disabled={role.builtin || !admin}><span><b>{role.name}</b><Tag tone={role.builtin ? 'blue' : 'purple'}>{role.builtin ? '内置' : '自定义'}</Tag></span><small>{role.description || '暂无描述'}</small><em>{role.permissions.length} 项业务权限</em></button>)}</div></Card><Card><SectionHead title="权限目录"/><div className="permission-summary">{Object.entries(modules).map(([id, label]) => <div key={id}><b>{label}</b>{data.catalog.filter(item => item.module === id).map(item => <span key={item.id}>{permissionLabels[item.id]}</span>)}</div>)}</div><div className="info-strip">角色和成员管理、最终验收、取消与重开始终保留给内置管理员，自定义角色不能获得这些敏感操作。</div></Card></div>
    </></ResourceState>
    {memberEditor && <MemberForm member={memberEditor} project={project} roles={data.roles} onClose={() => setMemberEditor(null)} onSaved={() => {setMemberEditor(null); resource.reload(); onMembershipChange();}}/>}
    {roleEditor && <RoleForm role={roleEditor.id ? roleEditor : null} project={project} catalog={data.catalog} onClose={() => setRoleEditor(null)} onSaved={() => {setRoleEditor(null); resource.reload();}}/>}
    {removing && <Modal title="移除项目成员" onClose={() => setRemoving(null)}><p>确认移除 {removing.name}？其任务与历史记录将保留。</p><ErrorNotice error={error}/><div className="editor-actions"><GhostButton onClick={() => setRemoving(null)}>取消</GhostButton><PrimaryButton icon={null} disabled={busy} onClick={remove}>确认移除</PrimaryButton></div></Modal>}
  </>;
}

function MemberForm({member, project, roles, onClose, onSaved}) {
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const body = Object.fromEntries(new FormData(event.currentTarget));
    try { await projectApi(project.id, '/members' + (member.id ? '/' + member.id : ''), {method: member.id ? 'PATCH' : 'POST', body}); onSaved(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  const current = member.role_key || member.role || 'member';
  return <Modal title={member.id ? `分配角色 · ${member.name}` : '添加成员'} onClose={onClose}><form onSubmit={submit}>{!member.id && <Field label="已有账号"><input name="username" required maxLength={200} placeholder="输入已开通的账号"/></Field>}<Field label="项目角色"><select name="role" defaultValue={current}>{roles.map(role => <option key={role.key} value={role.key}>{role.name}{role.builtin ? '（内置）' : '（自定义）'}</option>)}</select></Field><p className="muted">角色变更在保存后的下一次受保护请求生效；最后一名管理员不能降级。</p><ErrorNotice error={error}/><div className="editor-actions"><GhostButton type="button" onClick={onClose}>取消</GhostButton><PrimaryButton icon={null} disabled={busy}>{busy ? '保存中…' : '保存成员'}</PrimaryButton></div></form></Modal>;
}

function RoleForm({role, project, catalog, onClose, onSaved}) {
  const [selected, setSelected] = useState(new Set(role?.permissions || []));
  const [error, setError] = useState(null), [busy, setBusy] = useState(false);
  function toggle(permission, checked) {
    setSelected(current => {
      const next = new Set(current);
      if (checked) {
        next.add(permission);
        if (permission.endsWith('.write')) next.add(permission.replace('.write', '.read'));
        if (permission === 'requirement.history') next.add('requirement.read');
      } else {
        next.delete(permission);
        if (permission.endsWith('.read')) next.delete(permission.replace('.read', '.write'));
        if (permission === 'requirement.read') next.delete('requirement.history');
      }
      return next;
    });
  }
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      let target = role;
      if (!target) target = await projectApi(project.id, '/roles', {method: 'POST', body: {name: values.name, description: values.description}});
      await projectApi(project.id, '/roles/' + target.id, {method: 'PATCH', body: {name: values.name, description: values.description, permissions: [...selected], version: target.version}});
      onSaved();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={role ? `配置角色 · ${role.name}` : '新建自定义角色'} onClose={onClose}><form onSubmit={submit}><Field label="角色名称"><input name="name" defaultValue={role?.name || ''} required maxLength={200}/></Field><Field label="角色描述"><textarea name="description" defaultValue={role?.description || ''} maxLength={2000} rows={3}/></Field><div className="permission-editor">{Object.entries(modules).map(([moduleId, label]) => <fieldset key={moduleId}><legend>{label}</legend>{catalog.filter(item => item.module === moduleId).map(item => <label key={item.id}><input type="checkbox" checked={selected.has(item.id)} onChange={event => toggle(item.id, event.target.checked)}/><span>{permissionLabels[item.id]}</span></label>)}</fieldset>)}</div><p className="muted">勾选写权限会自动包含对应读取权限；未勾选的操作默认拒绝。</p><ErrorNotice error={error}/><div className="editor-actions"><GhostButton type="button" onClick={onClose}>取消</GhostButton><PrimaryButton icon={null} disabled={busy}>{busy ? '保存中…' : '保存角色'}</PrimaryButton></div></form></Modal>;
}
