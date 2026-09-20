import json
import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect, migrate
from app.main import COOKIE, create_app
from app.security import hash_password


class Sprint2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = hash_password(cls.password)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        migrate(self.path)
        with connect(self.path) as db:
            for name in ('admin', 'member', 'observer', 'outsider', 'second_admin'):
                db.execute('INSERT INTO users(username,name,password_hash) VALUES(?,?,?)', (name, name, self.password_hash))
            db.executemany('INSERT INTO projects(name) VALUES(?)', [('测试项目 A',), ('测试项目 B',)])
            db.executemany('INSERT INTO memberships(project_id,user_id,role,active) VALUES(?,?,?,1)', [
                (1, 1, 'admin'), (1, 2, 'member'), (1, 3, 'observer'), (1, 5, 'admin'), (2, 4, 'admin'),
            ])
        self.app = create_app(self.path)
        self.clients = []
        self.admin = self.login('admin')
        self.member = self.login('member')
        self.observer = self.login('observer')
        self.outsider = self.login('outsider')
        self.second_admin = self.login('second_admin')
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

    def requirement(self, client=None, title='需求 A'):
        response = (client or self.admin).post(self.base + '/requirements', json={
            'title': title, 'description': '需求描述', 'source': '测试来源',
            'priority': 'Must', 'acceptance_criteria': '给定条件时返回可验证结果',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def task(self, requirement=None, client=None, **extra):
        requirement = requirement or self.requirement()
        response = (client or self.admin).post(self.base + '/tasks', json={
            'title': '测试任务', 'requirement_id': requirement['id'], **extra,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def role(self, name='需求查看者'):
        created = self.admin.post(self.base + '/roles', json={'name': name, 'description': '自定义只读角色'})
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()

    def configure_role(self, role, permissions):
        response = self.admin.patch(self.base + '/roles/' + str(role['id']), json={
            'name': role['name'], 'description': role['description'],
            'permissions': permissions, 'version': role['version'],
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_tc22_tc23_create_configure_and_validate_custom_role(self):
        self.assertEqual(self.member.post(self.base + '/roles', json={'name': '越权角色'}).status_code, 403)
        role = self.role()
        self.assertEqual(role['permissions'], [])
        invalid = self.admin.patch(self.base + '/roles/' + str(role['id']), json={
            'name': role['name'], 'description': '', 'permissions': ['task.write'], 'version': 1,
        })
        self.assertEqual(invalid.status_code, 422)
        configured = self.configure_role(role, ['requirement.read', 'requirement.history', 'task.read'])
        self.assertEqual(configured['version'], 2)
        self.assertEqual(set(configured['permissions']), {'requirement.read', 'requirement.history', 'task.read'})
        self.assertEqual(self.admin.patch(self.base + '/roles/' + str(role['id']), json={
            'name': role['name'], 'description': '', 'permissions': [], 'version': 1,
        }).status_code, 409)
        duplicate = self.admin.post(self.base + '/roles', json={'name': role['name']})
        self.assertEqual(duplicate.status_code, 409)
        with connect(self.path) as db:
            self.assertGreaterEqual(db.execute("SELECT COUNT(*) FROM events WHERE entity_type='role'").fetchone()[0], 2)

    def test_tc25_assignment_is_immediate_scoped_and_cannot_elevate_sensitive_operations(self):
        req = self.requirement()
        task = self.task(req)
        role = self.configure_role(self.role('任务协作者'), ['requirement.read', 'task.read', 'task.write'])
        assigned = self.admin.patch(self.base + '/members/2', json={'role': role['key']})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(self.member.get(self.base + '/tasks').status_code, 200)
        self.assertEqual(self.member.get(self.base + '/requirements').status_code, 200)
        self.assertEqual(self.member.post(self.base + '/requirements', json={
            'title': '禁止写需求', 'description': 'x', 'source': 'x', 'acceptance_criteria': 'x',
        }).status_code, 403)
        started = self.member.patch(self.base + '/tasks/' + task['id'] + '/status', json={'status': '进行中', 'version': 1})
        self.assertEqual(started.status_code, 200, started.text)
        waiting = self.member.patch(self.base + '/tasks/' + task['id'] + '/status', json={'status': '待验收', 'version': 2})
        self.assertEqual(waiting.status_code, 200, waiting.text)
        self.assertEqual(self.member.patch(self.base + '/tasks/' + task['id'] + '/status', json={
            'status': '已完成', 'version': 3, 'acceptance_confirmed': True,
        }).status_code, 403)
        self.assertEqual(self.admin.patch(self.base + '/members/2', json={'role': 'observer'}).status_code, 200)
        self.assertEqual(self.member.patch(self.base + '/tasks/' + task['id'] + '/blocker', json={
            'blocked': True, 'reason': '失去写权限后尝试', 'version': 3,
        }).status_code, 403)
        self.assertEqual(self.admin.patch(self.base + '/members/1', json={'role': role['key']}).status_code, 200)
        self.assertEqual(self.second_admin.patch(self.base + '/members/5', json={'role': role['key']}).status_code, 409)
        self.assertEqual(self.outsider.patch('/api/projects/2/members/4', json={'role': role['key']}).status_code, 422)

    def test_tc18_tc19_requirement_version_priority_and_review_flag(self):
        req = self.requirement(title='可版本化需求')
        task = self.task(req, sprint='S2')
        edited = self.member.patch(self.base + '/requirements/' + req['id'], json={
            'title': '可版本化需求 二版', 'description': '补充边界说明', 'source': '评审结论',
            'priority': 'Should', 'acceptance_criteria': '成功、拒绝和边界路径均通过',
            'version': 1, 'reason': '产品评审确认范围变化',
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()['version'], 2)
        self.assertEqual(edited.json()['priority'], 'Should')
        stale = self.admin.patch(self.base + '/requirements/' + req['id'], json={
            'title': '旧提交', 'description': '旧值', 'source': '旧值', 'priority': 'Must',
            'acceptance_criteria': '不可覆盖', 'version': 1, 'reason': '并发旧提交',
        })
        self.assertEqual(stale.status_code, 409)
        invalid = self.admin.patch(self.base + '/requirements/' + req['id'], json={
            'title': '无验收条件', 'description': 'x', 'source': 'x', 'priority': 'Could',
            'acceptance_criteria': '   ', 'version': 2, 'reason': 'x',
        })
        self.assertEqual(invalid.status_code, 422)
        versions = self.observer.get(self.base + '/requirements/' + req['id'] + '/versions')
        self.assertEqual(versions.status_code, 200, versions.text)
        self.assertEqual([item['version'] for item in versions.json()], [2, 1])
        self.assertEqual(versions.json()[0]['changed_by_name'], 'member')
        self.assertTrue(versions.json()[0]['changed_at'])
        self.assertEqual(versions.json()[1]['reason'], '产品评审确认范围变化')
        linked = self.admin.get(self.base + '/tasks/' + task['id']).json()
        self.assertTrue(linked['review_required'])
        self.assertEqual(linked['status'], '待办')
        self.assertEqual(linked['sprint'], 'S2')
        with connect(self.path) as db:
            event_row = db.execute("SELECT * FROM events WHERE entity_type='requirement' AND event_type='updated'").fetchone()
            self.assertEqual(event_row['actor_id'], 2)
            self.assertEqual(json.loads(event_row['before_json'])['priority'], 'Must')

    def test_tc21_requirement_progress_is_live_and_project_scoped(self):
        req = self.requirement(title='进展需求')
        first = self.task(req, owner_id=2)
        second = self.task(req)
        initial = self.observer.get(self.base + '/requirements/' + req['id'] + '/progress')
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(initial.json()['active_count'], 2)
        self.assertEqual(initial.json()['completed_count'], 0)
        version = first['version']
        for status in ('进行中', '待验收'):
            response = self.admin.patch(self.base + '/tasks/' + first['id'] + '/status', json={'status': status, 'version': version})
            self.assertEqual(response.status_code, 200, response.text)
            version = response.json()['version']
        completed = self.admin.patch(self.base + '/tasks/' + first['id'] + '/status', json={
            'status': '已完成', 'version': version, 'acceptance_confirmed': True,
        })
        self.assertEqual(completed.status_code, 200, completed.text)
        with connect(self.path) as db:
            db.execute("UPDATE tasks SET cancelled_at='2026-10-01T00:00:00+00:00',cancelled_by=1,cancel_reason='前向兼容测试' WHERE pk=?", (int(second['id'].split('-')[1]),))
        refreshed = self.observer.get(self.base + '/requirements/' + req['id'] + '/progress').json()
        self.assertEqual(refreshed['completed_count'], 1)
        self.assertEqual(refreshed['active_count'], 1)
        self.assertEqual({item['id'] for item in refreshed['tasks']}, {first['id'], second['id']})
        self.assertTrue(next(item for item in refreshed['tasks'] if item['id'] == second['id'])['cancelled'])
        self.assertEqual(self.outsider.get(self.base + '/requirements/' + req['id'] + '/progress').status_code, 403)

    def test_tc07_combined_filters_and_status_summary_share_one_scope(self):
        req = self.requirement()
        alpha = self.task(req, title='登录接口联调', owner_id=2)
        beta = self.task(req, title='登录页面检查', owner_id=3)
        gamma = self.task(req, title='统计口径说明')
        moved = self.admin.patch(self.base + '/tasks/' + alpha['id'] + '/status', json={'status': '进行中', 'version': 1})
        self.assertEqual(moved.status_code, 200, moved.text)
        query = {'q': '登录', 'owner_id': '2', 'status': '进行中'}
        filtered = self.observer.get(self.base + '/tasks', params=query)
        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual([item['id'] for item in filtered.json()], [alpha['id']])
        summary = self.observer.get(self.base + '/statistics/completion', params=query)
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()['active_total'], 1)
        self.assertEqual(summary.json()['status_counts']['进行中'], 1)
        self.assertEqual(summary.json()['filters'], {'q': '登录', 'status': '进行中', 'owner_id': '2'})
        self.assertEqual(self.observer.get(self.base + '/tasks', params={'q': '不存在'}).json(), [])
        self.assertEqual(len(self.observer.get(self.base + '/tasks').json()), 3)
        self.assertEqual(self.outsider.get(self.base + '/tasks', params={'q': gamma['title']}).status_code, 403)
        self.assertEqual(self.observer.get(self.base + '/tasks', params={'owner_id': 'bad'}).status_code, 422)
        self.assertEqual(self.observer.get(self.base + '/statistics/completion', params={'status': '取消'}).status_code, 422)

    def test_tc09_dependencies_cycle_project_boundary_and_manual_blocker(self):
        req = self.requirement()
        first = self.task(req, title='前置任务', due_date='2026-10-01')
        second = self.task(req, title='后续任务', due_date='2026-10-02')
        added = self.member.post(self.base + '/tasks/' + second['id'] + '/dependencies', json={
            'depends_on_id': first['id'], 'reason': '需要先完成接口',
        })
        self.assertEqual(added.status_code, 201, added.text)
        self.assertTrue(added.json()['dependency_blocked'])
        self.assertFalse(added.json()['manually_blocked'])
        self.assertEqual(added.json()['due_date'], '2026-10-02')
        self.assertEqual(self.member.post(self.base + '/tasks/' + first['id'] + '/dependencies', json={
            'depends_on_id': first['id'], 'reason': '自依赖',
        }).status_code, 422)
        self.assertEqual(self.member.post(self.base + '/tasks/' + first['id'] + '/dependencies', json={
            'depends_on_id': second['id'], 'reason': '形成循环',
        }).status_code, 422)
        foreign_req = self.outsider.post('/api/projects/2/requirements', json={
            'title': '外部需求', 'description': 'x', 'source': 'x', 'acceptance_criteria': 'x',
        }).json()
        foreign_task = self.outsider.post('/api/projects/2/tasks', json={
            'title': '外部任务', 'requirement_id': foreign_req['id'],
        }).json()
        self.assertEqual(self.member.post(self.base + '/tasks/' + second['id'] + '/dependencies', json={
            'depends_on_id': foreign_task['id'], 'reason': '跨项目',
        }).status_code, 404)
        blocked = self.member.patch(self.base + '/tasks/' + second['id'] + '/blocker', json={
            'blocked': True, 'reason': '等待外部测试环境', 'version': second['version'],
        })
        self.assertEqual(blocked.status_code, 200, blocked.text)
        self.assertTrue(blocked.json()['manually_blocked'])
        self.assertTrue(blocked.json()['dependency_blocked'])
        removed = self.member.request('DELETE', self.base + '/tasks/' + second['id'] + '/dependencies/' + first['id'], json={
            'reason': '前置关系调整',
        })
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse(removed.json()['dependency_blocked'])
        self.assertTrue(removed.json()['manually_blocked'])
        with connect(self.path) as db:
            actions = {row['event_type'] for row in db.execute("SELECT event_type FROM events WHERE entity_type='task_dependency'")}
            self.assertEqual(actions, {'dependency_added', 'dependency_removed'})

    def test_tc20_controlled_source_change_preserves_old_and_new(self):
        first_req = self.requirement(title='原需求')
        second_req = self.requirement(title='新需求')
        task = self.task(first_req)
        changed = self.member.patch(self.base + '/tasks/' + task['id'] + '/source', json={
            'requirement_id': second_req['id'], 'version': 1, 'reason': '评审确认重新归类',
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['requirement_id'], second_req['id'])
        self.assertTrue(changed.json()['review_required'])
        self.assertEqual(self.member.patch(self.base + '/tasks/' + task['id'] + '/source', json={
            'requirement_id': first_req['id'], 'version': 1, 'reason': '旧版本提交',
        }).status_code, 409)
        with connect(self.path) as db:
            row = db.execute("SELECT * FROM events WHERE event_type='source_changed'").fetchone()
            self.assertEqual(json.loads(row['before_json'])['requirement_id'], first_req['id'])
            self.assertEqual(json.loads(row['after_json'])['requirement_id'], second_req['id'])
            self.assertEqual(row['reason'], '评审确认重新归类')

    def test_tc10_milestone_assignment_and_live_completion(self):
        self.assertEqual(self.member.post(self.base + '/milestones', json={
            'name': '越权里程碑', 'target_date': '2026-10-01',
        }).status_code, 403)
        created = self.admin.post(self.base + '/milestones', json={
            'name': 'Sprint 2 验收', 'target_date': '2026-10-10',
        })
        self.assertEqual(created.status_code, 201, created.text)
        milestone = created.json()
        empty = self.admin.post(self.base + '/milestones', json={
            'name': '空里程碑', 'target_date': '2026-10-20',
        }).json()
        self.assertEqual(empty['active_count'], 0)
        self.assertIsNone(empty['completion_rate'])
        req = self.requirement()
        first = self.task(req, milestone_id=milestone['id'])
        second = self.task(req)
        attached = self.member.patch(self.base + '/tasks/' + second['id'], json={
            'title': second['title'], 'description': second['description'], 'owner_id': None,
            'due_date': None, 'sprint': 'S2', 'milestone_id': milestone['id'], 'version': second['version'],
        })
        self.assertEqual(attached.status_code, 200, attached.text)
        foreign = self.outsider.post('/api/projects/2/milestones', json={
            'name': '外项目里程碑', 'target_date': '2026-10-11',
        }).json()
        self.assertEqual(self.member.patch(self.base + '/tasks/' + second['id'], json={
            'title': second['title'], 'description': second['description'], 'owner_id': None,
            'due_date': None, 'sprint': 'S2', 'milestone_id': foreign['id'], 'version': attached.json()['version'],
        }).status_code, 422)
        version = first['version']
        for status in ('进行中', '待验收'):
            response = self.admin.patch(self.base + '/tasks/' + first['id'] + '/status', json={'status': status, 'version': version})
            version = response.json()['version']
        self.admin.patch(self.base + '/tasks/' + first['id'] + '/status', json={
            'status': '已完成', 'version': version, 'acceptance_confirmed': True,
        })
        refreshed = self.observer.get(self.base + '/milestones').json()[0]
        self.assertEqual(refreshed['active_count'], 2)
        self.assertEqual(refreshed['completed_count'], 1)
        self.assertEqual(refreshed['completion_rate'], 50.0)
        details = self.observer.get(self.base + f"/milestones/{milestone['id']}/tasks").json()
        self.assertEqual({item['id'] for item in details}, {first['id'], second['id']})
        with connect(self.path) as db:
            db.execute("UPDATE tasks SET cancelled_at='2026-10-01T00:00:00+00:00',cancelled_by=1,cancel_reason='里程碑排除样例' WHERE pk=?", (int(second['id'].split('-')[1]),))
        recalculated = self.observer.get(self.base + '/milestones').json()[0]
        self.assertEqual(recalculated['active_count'], 1)
        self.assertEqual(recalculated['completion_rate'], 100.0)
        marked = self.observer.get(self.base + f"/milestones/{milestone['id']}/tasks").json()
        self.assertTrue(next(item for item in marked if item['id'] == second['id'])['cancelled'])

    def test_tc30_overall_completion_is_recomputable_and_empty_safe(self):
        req = self.requirement()
        tasks = [self.task(req, title=f'统计任务 {index}') for index in range(4)]
        for item in tasks[:2]:
            version = item['version']
            for status in ('进行中', '待验收'):
                response = self.admin.patch(self.base + '/tasks/' + item['id'] + '/status', json={'status': status, 'version': version})
                version = response.json()['version']
            self.admin.patch(self.base + '/tasks/' + item['id'] + '/status', json={
                'status': '已完成', 'version': version, 'acceptance_confirmed': True,
            })
        waiting = self.admin.patch(self.base + '/tasks/' + tasks[2]['id'] + '/status', json={'status': '进行中', 'version': 1}).json()
        self.admin.patch(self.base + '/tasks/' + tasks[2]['id'] + '/status', json={'status': '待验收', 'version': waiting['version']})
        with connect(self.path) as db:
            db.execute("UPDATE tasks SET cancelled_at='2026-10-01T00:00:00+00:00',cancelled_by=1,cancel_reason='统计排除样例' WHERE pk=?", (int(tasks[3]['id'].split('-')[1]),))
        result = self.observer.get(self.base + '/statistics/completion').json()
        self.assertEqual(result['active_total'], 3)
        self.assertEqual(result['completed'], 2)
        self.assertEqual(result['completion_rate'], 66.7)
        self.assertEqual(sum(result['status_counts'].values()), result['active_total'])
        completed_only = self.observer.get(self.base + '/statistics/completion', params={'status': '已完成'}).json()
        self.assertEqual(completed_only['active_total'], 2)
        self.assertEqual(completed_only['completion_rate'], 100.0)
        empty = self.outsider.get('/api/projects/2/statistics/completion')
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertIsNone(empty.json()['completion_rate'])

    def test_tc33_task_plan_member_capacity_and_versions(self):
        req = self.requirement()
        task = self.task(req, owner_id=2, due_date='2026-09-26', sprint='S2')
        planned = self.member.patch(self.base + '/tasks/' + task['id'] + '/plan', json={
            'estimated_hours': 12.5, 'actual_hours': 3, 'remaining_hours': 9.5,
            'planned_start': '2026-09-20', 'planned_end': '2026-09-24',
            'plan_locked': True, 'version': task['version'], 'reason': 'Sprint 2 排期确认',
        })
        self.assertEqual(planned.status_code, 200, planned.text)
        self.assertEqual(planned.json()['estimated_hours'], 12.5)
        self.assertEqual(planned.json()['actual_hours'], 3)
        self.assertEqual(planned.json()['remaining_hours'], 9.5)
        self.assertTrue(planned.json()['plan_locked'])
        self.assertEqual(self.member.patch(self.base + '/tasks/' + task['id'] + '/plan', json={
            'estimated_hours': -1, 'actual_hours': 0, 'remaining_hours': 0,
            'planned_start': None, 'planned_end': None, 'plan_locked': False,
            'version': planned.json()['version'],
        }).status_code, 422)
        self.assertEqual(self.member.patch(self.base + '/tasks/' + task['id'] + '/plan', json={
            'estimated_hours': 1, 'actual_hours': 0, 'remaining_hours': 1,
            'planned_start': '2026-09-24', 'planned_end': '2026-09-20', 'plan_locked': False,
            'version': planned.json()['version'],
        }).status_code, 422)
        self.assertEqual(self.member.patch(self.base + '/tasks/' + task['id'] + '/plan', json={
            'estimated_hours': 9, 'actual_hours': 3, 'remaining_hours': 6,
            'planned_start': None, 'planned_end': None, 'plan_locked': False,
            'version': task['version'],
        }).status_code, 409)

        before = next(item for item in self.member.get(self.base + '/members').json() if item['id'] == 2)
        self.assertIsNone(before['weekly_capacity_hours'])
        capacity = self.member.patch(self.base + '/members/2/capacity', json={
            'weekly_capacity_hours': 20, 'available_from': '2026-09-20', 'available_to': '2026-10-24',
            'skill_tags': ['React', 'FastAPI'], 'version': 0, 'reason': '本人确认可用容量',
        })
        self.assertEqual(capacity.status_code, 200, capacity.text)
        self.assertEqual(capacity.json()['capacity_version'], 1)
        self.assertEqual(capacity.json()['skill_tags'], ['React', 'FastAPI'])
        self.assertEqual(self.member.patch(self.base + '/members/2/capacity', json={
            'weekly_capacity_hours': 20, 'available_from': '2026-10-24', 'available_to': '2026-09-20',
            'skill_tags': [], 'version': 1,
        }).status_code, 422)
        self.assertEqual(self.member.patch(self.base + '/members/2/capacity', json={
            'weekly_capacity_hours': 20, 'available_from': None, 'available_to': None,
            'skill_tags': ['React', 'React'], 'version': 1,
        }).status_code, 422)
        self.assertEqual(self.observer.patch(self.base + '/members/2/capacity', json={
            'weekly_capacity_hours': 10, 'available_from': None, 'available_to': None,
            'skill_tags': [], 'version': 1,
        }).status_code, 403)
        with connect(self.path) as db:
            plan_event = db.execute("SELECT * FROM events WHERE entity_type='task' AND event_type='plan_updated'").fetchone()
            self.assertEqual(plan_event['actor_id'], 2)
            self.assertEqual(json.loads(plan_event['after_json'])['version'], 2)
            capacity_event = db.execute("SELECT * FROM events WHERE entity_type='member_capacity'").fetchone()
            self.assertEqual(capacity_event['reason'], '本人确认可用容量')

    def test_tc11_readonly_task_history_and_missing_baseline(self):
        req = self.requirement(title='历史需求')
        task = self.task(req, owner_id=2, due_date='2026-09-24')
        edited = self.member.patch(self.base + '/tasks/' + task['id'], json={
            'title': task['title'], 'description': '补充描述', 'owner_id': 2,
            'due_date': '2026-09-25', 'sprint': 'S2', 'milestone_id': None, 'version': task['version'],
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        moved = self.member.patch(self.base + '/tasks/' + task['id'] + '/status', json={
            'status': '进行中', 'version': edited.json()['version'],
        })
        self.assertEqual(moved.status_code, 200, moved.text)
        changed_req = self.member.patch(self.base + '/requirements/' + req['id'], json={
            'title': '历史需求二版', 'description': '范围改变', 'source': '复审', 'priority': 'Must',
            'acceptance_criteria': '新验收条件', 'version': 1, 'reason': '范围复审',
        })
        self.assertEqual(changed_req.status_code, 200, changed_req.text)
        history = self.observer.get(self.base + '/tasks/' + task['id'] + '/history')
        self.assertEqual(history.status_code, 200, history.text)
        self.assertTrue(history.json()['readonly'])
        self.assertEqual(history.json()['missing_records'], [])
        event_types = {item['event_type'] for item in history.json()['events']}
        self.assertTrue({'created', 'updated', 'status_changed', 'source_requirement_changed'}.issubset(event_types))
        self.assertTrue(all(item['actor_name'] and item['occurred_at'] for item in history.json()['events']))
        self.assertEqual(self.admin.patch(self.base + '/tasks/' + task['id'] + '/history', json={}).status_code, 405)
        self.assertEqual(self.outsider.get(self.base + '/tasks/' + task['id'] + '/history').status_code, 403)

        with connect(self.path) as db:
            raw_pk = db.execute('''INSERT INTO tasks(project_id,requirement_pk,title,description,sprint,created_by,created_at,updated_at)
                VALUES(1,?,?,?,?,?,?,?)''', (int(req['id'].split('-')[1]), '历史缺口样例', '', 'S2', 1,
                '2026-09-20T00:00:00+00:00', '2026-09-20T00:00:00+00:00')).lastrowid
        missing = self.observer.get(self.base + f'/tasks/T-{raw_pk:03d}/history')
        self.assertEqual(missing.status_code, 200, missing.text)
        self.assertTrue(missing.json()['missing_records'])
        self.assertEqual(missing.json()['events'], [])

    def test_tc27_tc28_cancel_reopen_and_completion_recalculation(self):
        req = self.requirement()
        cancelled = self.task(req, title='取消样例')
        self.assertEqual(self.member.patch(self.base + '/tasks/' + cancelled['id'] + '/cancel', json={
            'version': cancelled['version'], 'reason': '成员无权取消',
        }).status_code, 403)
        self.assertEqual(self.admin.patch(self.base + '/tasks/' + cancelled['id'] + '/cancel', json={
            'version': cancelled['version'], 'reason': '   ',
        }).status_code, 422)
        cancelled_response = self.admin.patch(self.base + '/tasks/' + cancelled['id'] + '/cancel', json={
            'version': cancelled['version'], 'reason': '范围确认后不再执行',
        })
        self.assertEqual(cancelled_response.status_code, 200, cancelled_response.text)
        self.assertTrue(cancelled_response.json()['cancelled'])
        self.assertEqual(cancelled_response.json()['status'], '待办')
        self.assertEqual(self.observer.get(self.base + '/tasks').json(), [])
        self.assertEqual([item['id'] for item in self.observer.get(self.base + '/tasks', params={'cancelled': 'only'}).json()], [cancelled['id']])
        self.assertEqual(self.admin.patch(self.base + '/tasks/' + cancelled['id'] + '/status', json={
            'status': '进行中', 'version': cancelled_response.json()['version'],
        }).status_code, 409)
        self.assertEqual(self.admin.patch(self.base + '/tasks/' + cancelled['id'] + '/reopen', json={
            'version': cancelled_response.json()['version'], 'reason': '取消任务不可恢复',
        }).status_code, 409)
        self.assertEqual(self.admin.delete(self.base + '/tasks/' + cancelled['id']).status_code, 405)

        completed = self.task(req, title='返工样例')
        version = completed['version']
        for status in ('进行中', '待验收'):
            response = self.admin.patch(self.base + '/tasks/' + completed['id'] + '/status', json={'status': status, 'version': version})
            version = response.json()['version']
        accepted = self.admin.patch(self.base + '/tasks/' + completed['id'] + '/status', json={
            'status': '已完成', 'version': version, 'acceptance_confirmed': True,
        }).json()
        self.assertEqual(self.observer.get(self.base + '/statistics/completion').json()['completion_rate'], 100.0)
        self.assertEqual(self.member.patch(self.base + '/tasks/' + completed['id'] + '/reopen', json={
            'version': accepted['version'], 'reason': '成员无权重开',
        }).status_code, 403)
        reopened = self.admin.patch(self.base + '/tasks/' + completed['id'] + '/reopen', json={
            'version': accepted['version'], 'reason': '验收后发现需返工',
        })
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(reopened.json()['status'], '进行中')
        summary = self.observer.get(self.base + '/statistics/completion').json()
        self.assertEqual(summary['completion_rate'], 0.0)
        self.assertEqual(summary['cancelled_count'], 1)
        self.assertEqual(summary['current_week']['timezone'], 'Asia/Shanghai')
        self.assertEqual(summary['current_week']['reopened_count'], 1)
        history = self.observer.get(self.base + '/tasks/' + completed['id'] + '/history').json()
        self.assertIn('accepted', {item['event_type'] for item in history['events']})
        self.assertIn('reopened', {item['event_type'] for item in history['events']})

        version = reopened.json()['version']
        waiting = self.admin.patch(self.base + '/tasks/' + completed['id'] + '/status', json={'status': '待验收', 'version': version}).json()
        reaccepted = self.admin.patch(self.base + '/tasks/' + completed['id'] + '/status', json={
            'status': '已完成', 'version': waiting['version'], 'acceptance_confirmed': True,
        }).json()
        cancelled_complete = self.admin.patch(self.base + '/tasks/' + completed['id'] + '/cancel', json={
            'version': reaccepted['version'], 'reason': '完成后范围撤销',
        })
        self.assertEqual(cancelled_complete.status_code, 200, cancelled_complete.text)
        final_summary = self.observer.get(self.base + '/statistics/completion').json()
        self.assertEqual(final_summary['cancelled_count'], 2)
        self.assertEqual(final_summary['cancelled_completed_count'], 1)
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE event_type='cancelled_completed'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
