import React, {useEffect, useRef} from 'react';
import {Card, GhostButton} from '../components';

export function ErrorNotice({error, retry}) {
  if (!error) return null;
  return <div role="alert" className="error-notice">{error.message || error}{retry && <GhostButton onClick={retry}>重试</GhostButton>}</div>;
}
export function Loading() { return <div className="empty-state" role="status">正在加载…</div>; }
export function Empty({children}) { return <div className="empty-state">{children}</div>; }
export function ResourceState({resource, children}) {
  if (resource.loading) return <Loading/>;
  if (resource.error) return <ErrorNotice error={resource.error} retry={resource.reload}/>;
  return children;
}
export function Modal({title, onClose, children}) {
  const ref = useRef(null);
  useEffect(() => { const dialog = ref.current; dialog.showModal(); return () => dialog.close(); }, []);
  return <dialog ref={ref} className="s1-modal" onCancel={onClose}><div className="drawer-top"><h2>{title}</h2><button type="button" aria-label="关闭" onClick={onClose}>×</button></div>{children}</dialog>;
}
export function Field({label, children}) { return <label className="s1-field"><span>{label}</span>{React.cloneElement(children, {'aria-label': label})}</label>; }
export function Preview({children, sprint}) {
  return <><Card className="preview-notice">设计预览 · {sprint} 后续接入。此页为原有示例数据，尚未连接当前项目。</Card><div inert className="design-preview">{children}</div></>;
}
