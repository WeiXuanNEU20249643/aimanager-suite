import json
import io
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from fastapi.testclient import TestClient
from app.db import connect, migrate
from app.main import COOKIE, create_app
from app.security import hash_password
from app.manage import main as manage


class Sprint1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = hash_password(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        migrate(self.path)
        with connect(self.path) as db:
            for name in ('admin', 'member', 'observer', 'outsider', 'new'):
                db.execute('INSERT INTO users(username,name,password_hash) VALUES(?,?,?)', (name, name, self.password_hash))
            db.executemany('INSERT INTO projects(name) VALUES(?)', [('测试项目 A',), ('测试项目 B',)])
            db.executemany('INSERT INTO memberships(project_id,user_id,role,active) VALUES(?,?,?,1)', [(1, 1, 'admin'), (1, 2, 'member'), (1, 3, 'observer'), (2, 4, 'admin')])
        self.app = create_app(self.path)
        self.clients = []
        self.admin = self.login('admin')
        self.member = self.login('member')
        self.observer = self.login('observer')
        self.outsider = self.login('outsider')
        self.base = '/api/projects/1'

    def tearDown(self):
        for client in self.clients:
            client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, username):
        client = TestClient(self.app, headers={'X-Requested-With': 'aimanager'})
        client.__enter__()
        self.clients.append(client)
        self.assertEqual(client.post('/api/auth/login', json={'username': username, 'password': self.password}).status_code, 200)
        return client

    def req(self, client=None, base=None):
        r = (client or self.admin).post((base or self.base) + '/requirements', json={'title': '测试需求', 'description': '独立来源描述', 'source': '测试访谈'})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def task(self, **kwargs):
        req = self.req()
        r = self.member.post(self.base + '/tasks', json={'title': '测试任务', 'requirement_id': req['id'], **kwargs})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def test_tc01_login_logout_refresh_and_generic_errors(self):
        cookie = self.admin.cookies.get(COOKIE)
        self.assertEqual(self.admin.get('/api/auth/me').json()['username'], 'admin')
        with TestClient(create_app(self.path), headers={'Cookie': f'{COOKIE}={cookie}'}) as restarted:
            self.assertEqual(restarted.get('/api/auth/me').status_code, 200)
        wrong = self.admin.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'})
        missing = self.admin.post('/api/auth/login', json={'username': 'unknown', 'password': 'wrong'})
        self.assertEqual(wrong.json(), missing.json())
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(self.admin.post('/api/auth/logout').status_code, 204)
        self.assertEqual(self.admin.get(self.base + '/tasks', headers={'Cookie': f'{COOKIE}={cookie}'}).status_code, 401)
        bad = self.admin.post('/api/auth/login', json={'username': '', 'password': self.password})
        self.assertNotIn(self.password, bad.text)

    def test_tc02_member_roles_duplicates_last_admin(self):
        self.assertEqual(self.admin.post(self.base + '/members', json={'username': 'new', 'role': 'member'}).status_code, 201)
        self.assertEqual(self.admin.post(self.base + '/members', json={'username': 'new', 'role': 'observer'}).status_code, 409)
        self.assertEqual(self.admin.patch(self.base + '/members/1', json={'role': 'member'}).status_code, 409)
        self.assertEqual(self.admin.delete(self.base + '/members/1').status_code, 409)
        self.assertEqual(self.member.post(self.base + '/members', json={'username': 'outsider', 'role': 'admin'}).status_code, 403)
        self.assertEqual(self.admin.patch(self.base + '/members/5', json={'role': 'admin'}).status_code, 200)
        self.assertEqual(self.admin.patch(self.base + '/members/1', json={'role': 'member'}).status_code, 200)
        self.assertEqual(self.admin.delete(self.base + '/members/5').status_code, 403)

    def test_tc02_removal_retains_owner_and_events(self):
        task = self.task(owner_id=2)
        self.assertEqual(self.admin.delete(self.base + '/members/2').status_code, 204)
        self.assertEqual(self.member.get(self.base + '/tasks').status_code, 403)
        saved = self.admin.get(self.base + '/tasks/' + task['id']).json()
        self.assertEqual(saved['owner_id'], 2)
        self.assertFalse(saved['owner_active'])
        with connect(self.path) as db:
            self.assertGreater(db.execute('SELECT COUNT(*) FROM events WHERE actor_id=2').fetchone()[0], 0)
        self.assertEqual(self.admin.post(self.base + '/members', json={'username': 'member', 'role': 'observer'}).status_code, 201)
        self.assertEqual(self.member.get(self.base + '/tasks').status_code, 200)
        self.assertEqual(self.member.post(self.base + '/requirements', json={'title': 'a', 'description': 'b', 'source': 'c'}).status_code, 403)

    def test_tc06_read_only_and_project_isolation(self):
        req = self.req()
        task = self.task()
        for path in ('', '/members', '/requirements', '/tasks', '/requirements/' + req['id'], '/tasks/' + task['id']):
            self.assertEqual(self.observer.get(self.base + path).status_code, 200)
            self.assertEqual(self.outsider.get(self.base + path).status_code, 403)
            with TestClient(self.app) as anonymous:
                self.assertEqual(anonymous.get(self.base + path).status_code, 401)
        self.assertEqual(self.observer.post(self.base + '/requirements', json={'title': 'a', 'description': 'b', 'source': 'c'}).status_code, 403)
        self.assertEqual(self.observer.post(self.base + '/tasks', json={'title': 'a', 'requirement_id': req['id']}).status_code, 403)
        self.assertEqual(self.observer.patch(self.base + '/tasks/' + task['id'] + '/status', json={'status': '进行中', 'version': 1}).status_code, 403)
        self.assertEqual(self.observer.delete(self.base + '/members/2').status_code, 403)
        for path in ('/api/requirements', '/api/tasks', '/api/project', '/api/ai/analysis'):
            self.assertEqual(self.outsider.get(path).status_code, 404)
        self.assertEqual(self.outsider.get('/api/projects').json()[0]['id'], 2)

    def test_tc16_tc17_requirements_search_stable_id_and_validation(self):
        req = self.req(self.member)
        self.assertEqual(req['version'], 1)
        self.assertEqual(req['created_by'], 2)
        for query in (req['id'], '独立来源', '访谈'):
            self.assertEqual(self.admin.get(self.base + '/requirements', params={'q': query}).json()[0]['id'], req['id'])
        self.assertEqual(self.admin.get(self.base + '/requirements?q=不存在').json(), [])
        for field in ('title', 'description', 'source'):
            data = {'title': 'a', 'description': 'b', 'source': 'c', field: '   '}
            self.assertEqual(self.admin.post(self.base + '/requirements', json=data).status_code, 422)
        self.assertNotEqual(self.req()['id'], req['id'])
        with TestClient(create_app(self.path), headers={'Cookie': f'{COOKIE}={self.admin.cookies.get(COOKIE)}'}) as restarted:
            self.assertEqual(restarted.get(self.base + '/requirements/' + req['id']).json(), req)
        with connect(self.path) as db:
            e = db.execute("SELECT * FROM events WHERE entity_type='requirement' AND entity_id=?", (req['id'],)).fetchone()
            self.assertEqual(e['actor_id'], 2)
            self.assertEqual(json.loads(e['after_json'])['version'], 1)

    def test_tc03_task_source_and_invalid_input_no_residue(self):
        foreign = self.req(self.outsider, '/api/projects/2')
        for rid in (foreign['id'], 'REQ-999', 'bad'):
            self.assertEqual(self.member.post(self.base + '/tasks', json={'title': '任务', 'requirement_id': rid}).status_code, 404)
        req = self.req()
        for extra in ({'title': ''}, {'owner_id': 4}, {'sprint': 'S7'}, {'due_date': '2026-02-30'}, {'owner_id': [1, 2]}, {'status': '已完成'}):
            self.assertEqual(self.member.post(self.base + '/tasks', json={'title': '任务', 'requirement_id': req['id'], **extra}).status_code, 422)
        self.assertEqual(self.admin.get(self.base + '/tasks').json(), [])
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE entity_type='task'").fetchone()[0], 0)

    def test_tc04_edit_flow_acceptance_and_stale_versions(self):
        t = self.task()
        url = self.base + '/tasks/' + t['id']
        body = {'title': '修改标题', 'description': '修改内容', 'owner_id': 2, 'due_date': '2026-10-01', 'sprint': 'S6', 'version': 1}
        self.assertEqual(self.member.patch(url, json=body).status_code, 200)
        self.assertEqual(self.member.patch(url, json=body).status_code, 409)
        self.assertEqual(self.member.patch(url + '/status', json={'status': '已完成', 'version': 2}).status_code, 409)
        self.assertEqual(self.member.patch(url + '/status', json={'status': '进行中', 'version': 2}).status_code, 200)
        self.assertEqual(self.member.patch(url + '/status', json={'status': '待办', 'version': 3}).status_code, 422)
        self.assertEqual(self.member.patch(url + '/status', json={'status': '待办', 'version': 3, 'reason': '补充描述'}).status_code, 200)
        self.assertEqual(self.member.patch(url + '/status', json={'status': '进行中', 'version': 4}).status_code, 200)
        self.assertEqual(self.member.patch(url + '/status', json={'status': '待验收', 'version': 5}).status_code, 200)
        self.assertEqual(self.member.patch(url + '/status', json={'status': '已完成', 'version': 6, 'acceptance_confirmed': True}).status_code, 403)
        self.assertEqual(self.admin.patch(url + '/status', json={'status': '已完成', 'version': 6}).status_code, 422)
        self.assertEqual(self.admin.patch(url + '/status', json={'status': '已完成', 'version': 6, 'acceptance_confirmed': True}).status_code, 200)
        self.assertEqual(self.admin.patch(url + '/status', json={'status': '进行中', 'version': 7}).status_code, 409)
        self.assertEqual(self.admin.get(url).json()['status'], '已完成')
        with connect(self.path) as db:
            e = db.execute("SELECT * FROM events WHERE event_type='accepted'").fetchone()
            self.assertEqual(e['actor_id'], 1)
            self.assertEqual(json.loads(e['before_json'])['status'], '待验收')
            self.assertEqual(json.loads(e['after_json'])['status'], '已完成')
            self.assertTrue(e['occurred_at'])

    def test_tc04_atomic_failure_and_append_only(self):
        t = self.task()
        with patch('app.main.event', side_effect=sqlite3.OperationalError('injected failure')):
            response = self.member.patch(self.base + '/tasks/' + t['id'] + '/status', json={'status': '进行中', 'version': 1})
            self.assertEqual(response.status_code, 503)
            response = self.admin.post(self.base + '/requirements', json={'title': '失败需求', 'description': 'b', 'source': 'c'})
            self.assertEqual(response.status_code, 503)
        self.assertEqual(self.member.get(self.base + '/tasks/' + t['id']).json()['version'], 1)
        self.assertEqual(self.admin.get(self.base + '/requirements?q=失败需求').json(), [])
        with connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE events SET reason='tamper'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM events')

    def test_tc29_shared_list_detail_and_persistence(self):
        t = self.task(owner_id=2)
        self.assertEqual(self.member.get(self.base + '/tasks').json(), [self.member.get(self.base + '/tasks/' + t['id']).json()])
        migrate(self.path)
        with TestClient(create_app(self.path), headers={'Cookie': f'{COOKIE}={self.member.cookies.get(COOKIE)}'}) as restarted:
            self.assertEqual(restarted.get(self.base + '/tasks').json()[0]['id'], t['id'])

    def test_session_expiry_csrf_and_live_demotion(self):
        with connect(self.path) as db:
            db.execute('UPDATE sessions SET expires_at=0 WHERE user_id=2')
        self.assertEqual(self.member.get(self.base + '/tasks').status_code, 401)
        with TestClient(self.app) as client:
            self.assertEqual(client.post('/api/auth/logout').status_code, 403)
        self.assertEqual(self.admin.patch(self.base + '/members/2', json={'role': 'observer'}).status_code, 200)
        member = self.login('member')
        self.assertEqual(member.post(self.base + '/requirements', json={'title': 'a', 'description': 'b', 'source': 'c'}).status_code, 403)

    def test_concurrent_admin_demotion_and_task_updates(self):
        self.assertEqual(self.admin.patch(self.base + '/members/2', json={'role': 'admin'}).status_code, 200)
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(client.patch, self.base + f'/members/{uid}', json={'role': 'member'}) for client, uid in [(self.admin, 1), (self.member, 2)]]
            self.assertEqual(sorted(call.result().status_code for call in calls), [200, 409])
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM memberships WHERE project_id=1 AND role='admin' AND active=1").fetchone()[0], 1)
        t = self.task()
        body = {'title': '并发编辑', 'description': '', 'owner_id': None, 'due_date': None, 'sprint': 'S1', 'version': 1}
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(client.patch, self.base + '/tasks/' + t['id'], json=body) for client in (self.admin, self.member)]
            self.assertEqual(sorted(call.result().status_code for call in calls), [200, 409])
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE entity_id=? AND event_type='updated'", (t['id'],)).fetchone()[0], 1)

    def test_task_creation_rollback_and_large_identifiers(self):
        req = self.req()
        with patch('app.main.event', side_effect=sqlite3.OperationalError('injected failure')):
            response = self.member.post(self.base + '/tasks', json={'title': '回滚测试', 'requirement_id': req['id']})
            self.assertEqual(response.status_code, 503)
        self.assertEqual(self.admin.get(self.base + '/tasks').json(), [])
        self.assertEqual(self.admin.get(self.base + '/requirements/REQ-99999999999999999999999999').status_code, 404)
        self.assertEqual(self.admin.get(self.base + '/tasks/T-0001').status_code, 404)

    def test_empty_database_cli_bootstrap_without_password_output(self):
        fresh = Path(self.temp.name) / 'fresh.sqlite3'
        output = io.StringIO()
        with patch.dict('os.environ', {'AIMANAGER_DB': str(fresh)}), redirect_stdout(output):
            with patch('sys.argv', ['manage', 'create-user', 'first_admin', '--name', '初始管理员']), patch('getpass.getpass', return_value=self.password):
                manage()
            with patch('sys.argv', ['manage', 'create-project', '空环境测试项目', '--admin', 'first_admin']):
                manage()
            with patch('sys.argv', ['manage', 'migrate']):
                manage()
        self.assertNotIn(self.password, output.getvalue())
        with connect(fresh) as db:
            self.assertEqual(db.execute('SELECT role FROM memberships').fetchone()[0], 'admin')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)
            self.assertNotEqual(db.execute('SELECT password_hash FROM users').fetchone()[0], self.password)


if __name__ == '__main__':
    unittest.main()
