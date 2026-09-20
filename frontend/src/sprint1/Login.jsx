import React, {useState} from 'react';
import {Brand, Card, icons} from '../components';
import {api} from '../api';
import {ErrorNotice} from './ui';
const {TrendingUp, Database, Sparkles} = icons;

export function Login({onLogin}) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(null);
    const form = new FormData(e.currentTarget);
    try {
      const user = await api('/auth/login', {method: 'POST', body: {username: form.get('username'), password: form.get('password')}});
      onLogin(user);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <div className="login-page"><div className="login-left"><div className="login-brand"><Brand/></div><h1>让项目更简单</h1><p>连接需求、任务与团队协作，<br/>让每一次交付有据可循。</p><div className="feature-row">{[[TrendingUp, '可视化', '清晰掌握项目进度'], [Database, '一体化', '连接需求、任务和成员'], [Sparkles, 'AI化', '逐步接入智能辅助']].map(([Icon, title, text]) => <Card className="feature" key={title}><div className="feature-icon"><Icon size={22}/></div><b>{title}</b><span>{text}</span></Card>)}</div><Card className="login-preview"><b>项目概览</b><div className="mini-metrics"><i/><i/><i/><i/></div><div className="mini-chart"/><div className="mini-list"/></Card><div className="mountain-bg"><i/><i/><i/></div></div><div className="login-right"><Card className="login-card"><h2>欢迎登录爱管理</h2><p>高效的项目管理，从这里开始</p><form className="login-form" onSubmit={submit}><label>账号 / 邮箱<input name="username" autoComplete="username" required maxLength={200} placeholder="请输入账号或邮箱"/></label><label>密码<input name="password" type="password" autoComplete="current-password" required maxLength={1024} placeholder="请输入密码"/></label><ErrorNotice error={error}/><button className="login-submit" disabled={busy}>{busy ? '登录中…' : '登 录'}</button></form><small>如需开通账号或重置密码，请联系管理员。</small></Card></div></div>;
}
