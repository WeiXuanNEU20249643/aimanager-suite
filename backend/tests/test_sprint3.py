import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect, migrate
from app.main import create_app
from app.security import hash_password


class Sprint3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = hash_password(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        migrate(self.path)
        with connect(self.path) as db:
            for name in ('admin', 'member', 'observer', 'outsider'):
                db.execute('INSERT INTO users(username,name,password_hash) VALUES(?,?,?)',
                           (name, name, self.password_hash))
            db.executemany('INSERT INTO projects(name) VALUES(?)', [('项目 A',), ('项目 B',)])
            db.executemany('INSERT INTO memberships(project_id,user_id,role,active) VALUES(?,?,?,1)', [
                (1, 1, 'admin'), (1, 2, 'member'), (1, 3, 'observer'), (2, 4, 'admin'),
            ])
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
        response = client.post('/api/auth/login', json={'username': username, 'password': self.password})
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def requirement(self, title='Sprint 3 需求'):
        response = self.admin.post(self.base + '/requirements', json={
            'title': title, 'description': '需要真实联动排期', 'source': 'Sprint 3 测试',
            'priority': 'Must', 'acceptance_criteria': '三视图读取同一任务数据',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def task(self, requirement, title, owner_id=2, **extra):
        response = self.admin.post(self.base + '/tasks', json={
            'title': title, 'requirement_id': requirement['id'], 'owner_id': owner_id, **extra,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def capacity(self, user_id=2, weekly=20, end='2027-12-31'):
        response = self.admin.patch(self.base + f'/members/{user_id}/capacity', json={
            'weekly_capacity_hours': weekly, 'available_from': '2026-01-01',
            'available_to': end, 'skill_tags': ['FastAPI'], 'version': 0,
            'reason': '配置 Sprint 3 排期容量',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def set_plan(self, item, start, end, locked=False, estimated=8, remaining=8):
        response = self.admin.patch(self.base + f"/tasks/{item['id']}/plan", json={
            'estimated_hours': estimated, 'actual_hours': 0, 'remaining_hours': remaining,
            'planned_start': start, 'planned_end': end, 'plan_locked': locked,
            'version': item['version'], 'reason': '设置测试排期',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def edit_requirement(self, item):
        response = self.member.patch(self.base + f"/requirements/{item['id']}", json={
            'title': item['title'] + ' 二版', 'description': '确认工作量与优先级变化',
            'source': item['source'], 'priority': 'Should',
            'acceptance_criteria': item['acceptance_criteria'], 'version': item['version'],
            'reason': '确认 Sprint 3 排期影响',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_tc34_tc35_shared_planning_query_dates_dependencies_and_workload(self):
        req = self.requirement()
        first = self.set_plan(self.task(req, '接口实现'), '2026-09-28', '2026-09-29', estimated=8, remaining=6)
        second = self.set_plan(self.task(req, '页面联调'), '2026-09-30', '2026-10-02', estimated=12, remaining=10)
        unplanned = self.task(req, '待排期任务', owner_id=None)
        dependency = self.member.post(self.base + f"/tasks/{second['id']}/dependencies", json={
            'depends_on_id': first['id'], 'reason': '页面依赖接口',
        })
        self.assertEqual(dependency.status_code, 201, dependency.text)
        self.capacity()
        snapshot = self.observer.get(self.base + '/planning')
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        data = snapshot.json()
        self.assertEqual({item['id'] for item in data['tasks']}, {first['id'], second['id'], unplanned['id']})
        linked = next(item for item in data['tasks'] if item['id'] == second['id'])
        self.assertEqual(linked['planned_start'], '2026-09-30')
        self.assertEqual(linked['dependencies'][0]['id'], first['id'])
        self.assertEqual(data['unscheduled_task_ids'], [unplanned['id']])
        member = next(item for item in data['members'] if item['id'] == 2)
        self.assertEqual(member['task_count'], 2)
        self.assertEqual(member['workload_hours'], 16.0)
        self.assertGreater(member['capacity_hours'], 0)
        self.assertEqual(data['unassigned']['task_count'], 1)
        self.assertEqual(self.outsider.get(self.base + '/planning').status_code, 403)

    def test_tc35_removed_owner_and_cancelled_task_are_distinguished(self):
        req = self.requirement()
        retained = self.task(req, '保留历史负责人')
        cancelled = self.task(req, '已取消任务')
        cancelled_response = self.admin.patch(self.base + f"/tasks/{cancelled['id']}/cancel", json={
            'version': cancelled['version'], 'reason': '取消后不占未来容量',
        })
        self.assertEqual(cancelled_response.status_code, 200, cancelled_response.text)
        removed = self.admin.delete(self.base + '/members/2')
        self.assertEqual(removed.status_code, 204, removed.text)
        snapshot = self.observer.get(self.base + '/planning').json()
        owner = next(item for item in snapshot['members'] if item['id'] == 2)
        self.assertFalse(owner['active'])
        self.assertEqual(owner['role_name'], '成员')
        self.assertEqual(snapshot['cancelled_count'], 1)
        self.assertEqual([item['id'] for item in snapshot['tasks']], [retained['id']])

    def test_tc36_requirement_replan_is_atomic_versioned_and_preserves_locked_work(self):
        req = self.requirement()
        self.capacity()
        locked = self.set_plan(self.task(req, '已锁定接口'), '2026-09-28', '2026-09-30', locked=True)
        movable = self.set_plan(self.task(req, '可重排页面'), '2026-10-01', '2026-10-02', estimated=12, remaining=12)
        dependency = self.member.post(self.base + f"/tasks/{movable['id']}/dependencies", json={
            'depends_on_id': locked['id'], 'reason': '页面依赖锁定接口',
        })
        self.assertEqual(dependency.status_code, 201, dependency.text)
        req = self.edit_requirement(req)
        impact = self.observer.get(self.base + f"/requirements/{req['id']}/planning-impact")
        self.assertEqual(impact.status_code, 200, impact.text)
        impact_data = impact.json()
        self.assertEqual(impact_data['impacted_task_count'], 2)
        self.assertEqual([item['id'] for item in impact_data['preserved']], [locked['id']])
        body = {'requirement_version': req['version'], 'plan_version': impact_data['plan']['version'],
                'reason': '管理员确认需求变更并重算'}
        self.assertEqual(self.member.post(self.base + f"/requirements/{req['id']}/replan", json=body).status_code, 403)
        applied = self.admin.post(self.base + f"/requirements/{req['id']}/replan", json=body)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertTrue(applied.json()['applied'])
        locked_after = self.admin.get(self.base + f"/tasks/{locked['id']}").json()
        movable_after = self.admin.get(self.base + f"/tasks/{movable['id']}").json()
        self.assertEqual((locked_after['planned_start'], locked_after['planned_end']), ('2026-09-28', '2026-09-30'))
        self.assertGreater(movable_after['planned_start'], locked_after['planned_end'])
        self.assertEqual(movable_after['status'], '待办')
        self.assertFalse(movable_after['review_required'])
        runs = self.observer.get(self.base + f"/requirements/{req['id']}/planning-runs").json()
        self.assertTrue(runs[0]['applied'])
        self.assertEqual(runs[0]['requirement_version'], 2)
        history = self.observer.get(self.base + f"/tasks/{movable['id']}/history").json()
        self.assertIn('plan_recalculated', {item['event_type'] for item in history['events']})
        self.assertEqual(self.admin.post(self.base + f"/requirements/{req['id']}/replan", json=body).status_code, 409)

    def test_tc36_conflict_returns_reasons_without_partial_task_updates(self):
        req = self.requirement('冲突需求')
        self.capacity()
        assigned = self.set_plan(self.task(req, '已有排期'), '2026-10-05', '2026-10-06')
        unassigned = self.set_plan(self.task(req, '未分配工作', owner_id=None), '2026-10-07', '2026-10-08')
        req = self.edit_requirement(req)
        impact = self.admin.get(self.base + f"/requirements/{req['id']}/planning-impact").json()
        result = self.admin.post(self.base + f"/requirements/{req['id']}/replan", json={
            'requirement_version': req['version'], 'plan_version': impact['plan']['version'],
            'reason': '验证冲突时不部分更新',
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()['applied'])
        self.assertIn('unassigned', {item['type'] for item in result.json()['conflicts']})
        assigned_after = self.admin.get(self.base + f"/tasks/{assigned['id']}").json()
        unassigned_after = self.admin.get(self.base + f"/tasks/{unassigned['id']}").json()
        self.assertEqual((assigned_after['planned_start'], assigned_after['planned_end']), ('2026-10-05', '2026-10-06'))
        self.assertEqual((unassigned_after['planned_start'], unassigned_after['planned_end']), ('2026-10-07', '2026-10-08'))

    def test_tc37_board_change_advances_shared_version_and_same_task_snapshot(self):
        req = self.requirement()
        item = self.task(req, '看板联动任务')
        before = self.observer.get(self.base + '/planning').json()
        moved = self.member.patch(self.base + f"/tasks/{item['id']}/status", json={
            'status': '进行中', 'version': item['version'],
        })
        self.assertEqual(moved.status_code, 200, moved.text)
        after = self.observer.get(self.base + '/planning').json()
        self.assertGreater(after['plan']['version'], before['plan']['version'])
        refreshed = next(task for task in after['tasks'] if task['id'] == item['id'])
        self.assertEqual(refreshed['status'], '进行中')
        self.assertEqual(refreshed['version'], moved.json()['version'])


if __name__ == '__main__':
    unittest.main()
