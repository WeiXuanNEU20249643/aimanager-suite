import {useCallback, useEffect, useState} from 'react';

export const roles = {admin: '管理员', member: '成员', observer: '观察者'};
export const statuses = ['待办', '进行中', '待验收', '已完成'];
export const tones = {待办: 'gray', 进行中: 'blue', 待验收: 'purple', 已完成: 'green'};
export const ownerLabel = task => task.owner_id ? `${task.owner_name}${task.owner_active ? '' : '（已移除）'}` : '未分配';
export const dateTime = value => new Date(value).toLocaleString('zh-CN', {hour12: false});
export const can = (project, permission) => Boolean(project?.permissions?.includes(permission));
export const roleLabel = project => project?.role_name || roles[project?.role] || '项目成员';

export function useResource(loader, deps) {
  const [state, setState] = useState({data: null, error: null, loading: true});
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(x => x + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    setState({data: null, error: null, loading: true});
    loader(controller.signal).then(data => {
      if (!controller.signal.aborted) setState({data, error: null, loading: false});
    }).catch(error => {
      if (!controller.signal.aborted) setState({data: null, error, loading: false});
    });
    return () => controller.abort();
  }, [...deps, revision]);
  return {...state, reload};
}

export function readRoute() {
  const [path, search = ''] = location.hash.slice(1).split('?');
  const [page = 'overview', id] = path.split('/');
  const params = new URLSearchParams(search);
  return {page: page || 'overview', id, projectId: Number(params.get('project')) || null,
    requirementId: params.get('requirement'), q: params.get('q') || '',
    status: params.get('status') || '', ownerId: params.get('owner_id') || '',
    cancelled: params.get('cancelled') || 'active'};
}

export function navigate(page, projectId, requirementId) {
  const params = new URLSearchParams();
  if (projectId) params.set('project', projectId);
  if (requirementId) params.set('requirement', requirementId);
  location.hash = page + (params.size ? '?' + params : '');
}
