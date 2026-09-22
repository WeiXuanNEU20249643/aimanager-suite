import React, {lazy, Suspense, useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Shell, Card, GhostButton, Tag} from './components';
import {api} from './api';
import {Login} from './sprint1/Login';
import {Requirements} from './sprint1/Requirements';
import {Permissions} from './sprint1/Permissions';
import {Tasks} from './sprint1/Tasks';
import {Overview} from './sprint2/Overview';
import {Gantt} from './sprint3/Gantt';
import {MemberTasks} from './sprint3/MemberTasks';
import {UML} from './sprint4/UML';
import {AIAnalysis} from './sprint5/AIAnalysis';
import {readRoute, navigate, roleLabel, useResource} from './sprint1/shared';
import {Empty, ErrorNotice, Loading, Preview} from './sprint1/ui';
import './styles.css';
import './sprint1/styles.css';
import './sprint3/styles.css';
import './sprint4/styles.css';
import './sprint5/styles.css';
import './sprint6/styles.css';

const previewNames = {settings: 'SettingsPage'};
const previews = Object.fromEntries(Object.entries(previewNames).map(([key, name]) => [key, lazy(() => import('./pages').then(module => ({default: module[name]})))]));

function App() {
  const [route, setRoute] = useState(readRoute);
  const [user, setUser] = useState(null), [ready, setReady] = useState(false), [error, setError] = useState(null);
  async function restore() {
    setError(null);
    try { setUser(await api('/auth/me')); }
    catch (err) { if (err.status !== 401) setError(err); else setUser(null); }
    finally { setReady(true); }
  }
  useEffect(() => { restore(); const change = () => setRoute(readRoute()); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change); }, []);
  useEffect(() => { const denied = e => { if (e.detail === 401) setUser(null); }; window.addEventListener('api-access-error', denied); return () => window.removeEventListener('api-access-error', denied); }, []);
  if (!ready) return <Loading/>;
  if (error) return <div className="startup-state"><ErrorNotice error={error} retry={restore}/></div>;
  if (!user) return <Login onLogin={setUser}/>;
  return <Workspace user={user} route={route} onLogout={async () => {await api('/auth/logout', {method: 'POST'}); setUser(null); navigate('login');}}/>;
}

function Workspace({user, route, onLogout}) {
  const projects = useResource(signal => api('/projects', {signal}), [user.id]);
  const [error, setError] = useState(null);
  useEffect(() => { const denied = e => { if (e.detail === 403) projects.reload(); }; window.addEventListener('api-access-error', denied); return () => window.removeEventListener('api-access-error', denied); }, [projects.reload]);
  const project = projects.data?.find(p => p.id === route.projectId) || (!route.projectId ? projects.data?.[0] : null);
  useEffect(() => { if (project && (!route.projectId || route.page === 'login')) navigate(route.page === 'login' ? 'overview' : route.page + (route.id ? '/' + route.id : ''), project.id, route.requirementId); }, [project?.id, route.projectId, route.page]);
  async function logout() {setError(null); try {await onLogout();} catch (err) {setError(err);}}
  const preview = previews[route.page];
  const PreviewPage = preview;
  return <Shell active={route.page === 'tasks' ? 'kanban' : route.page} onNavigate={p => navigate(p, project?.id)} user={user} projects={projects.data || []} projectId={project?.id} role={roleLabel(project)} onProjectChange={id => navigate(route.page === 'login' ? 'overview' : route.page, id)} onLogout={logout}><ErrorNotice error={error}/>{projects.loading ? <Loading/> : projects.error ? <ErrorNotice error={projects.error} retry={projects.reload}/> : !project ? <Card><Empty>{projects.data.length ? '此项目不存在或您已无访问权限，请在顶部选择项目。' : '暂无获授权项目，请联系管理员将您的账号加入项目。'}</Empty><GhostButton onClick={projects.reload}>刷新项目权限</GhostButton></Card> : <div key={`${project.id}-${project.role}-${project.role_id || ''}`}>
    {route.page === 'requirements' ? <Requirements project={project} route={route}/> : ['kanban','tasks'].includes(route.page) ? <Tasks project={project} route={route}/> : route.page === 'gantt' ? <Gantt project={project}/> : route.page === 'members' ? <MemberTasks project={project}/> : route.page === 'uml' ? <UML project={project}/> : route.page === 'ai' ? <AIAnalysis project={project}/> : route.page === 'permissions' ? <Permissions project={project} onMembershipChange={projects.reload}/> : preview ? <Suspense fallback={<Loading/>}><Preview sprint="后续迭代"><PreviewPage/></Preview></Suspense> : ['overview','login'].includes(route.page) ? <Overview project={project}/> : <Card><Empty>页面不存在</Empty><GhostButton onClick={() => navigate('overview',project.id)}>返回概览</GhostButton></Card>}
  </div>}</Shell>;
}
createRoot(document.getElementById('root')).render(<App/>);

