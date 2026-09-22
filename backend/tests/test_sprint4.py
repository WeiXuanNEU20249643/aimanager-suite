import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect, migrate
from app.main import create_app
from app.security import hash_password


class Sprint4Tests(unittest.TestCase):
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

    def requirement(self, title, role=''):
        response = self.admin.post(self.base + '/requirements', json={
            'title': title, 'description': 'Sprint 4 UML 来源故事', 'source': 'Sprint 4 测试',
            'priority': 'Must', 'acceptance_criteria': '图中来源编号可追溯', 'story_role': role,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def task(self, source, title):
        response = self.admin.post(self.base + '/tasks', json={
            'title': title, 'requirement_id': source['id'], 'owner_id': 2, 'sprint': 'S4',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def scenario_body(self, name, task_id, second_task_id=None):
        messages = [{
            'from_participant': '产品负责人', 'to_participant': '前端页面',
            'label': '提交业务数据', 'branch_condition': '', 'task_id': task_id,
        }, {
            'from_participant': '前端页面', 'to_participant': '服务端 API',
            'label': '校验并保存', 'branch_condition': '权限有效',
            'task_id': second_task_id or task_id,
        }]
        return {'name': name, 'description': '显式记录参与者、消息顺序和来源任务',
                'participants': ['产品负责人', '前端页面', '服务端 API'], 'messages': messages}

    def test_tc38_use_case_generation_is_traceable_versioned_and_project_scoped(self):
        first = self.requirement('登记需求', '产品负责人')
        second = self.requirement('验收任务', '项目管理员')
        missing = self.requirement('待确认业务角色')
        first_task = self.task(first, '实现需求登记')
        second_task = self.task(second, '实现任务验收')

        center = self.observer.get(self.base + '/uml')
        self.assertEqual(center.status_code, 200, center.text)
        self.assertIsNone(center.json()['use_case'])
        self.assertEqual(self.observer.post(self.base + '/uml/use-case/generate', json={
            'source_version': center.json()['source_version'],
        }).status_code, 403)
        generated = self.member.post(self.base + '/uml/use-case/generate', json={
            'source_version': center.json()['source_version'],
        })
        self.assertEqual(generated.status_code, 200, generated.text)
        data = generated.json()
        self.assertTrue(data['content']['coverage']['passed'])
        self.assertEqual({item['name'] for item in data['content']['actors']}, {'产品负责人', '项目管理员'})
        first_case = next(item for item in data['content']['use_cases'] if item['id'] == first['id'])
        self.assertEqual(first_case['tasks'][0]['id'], first_task['id'])
        self.assertEqual(next(item for item in data['content']['use_cases'] if item['id'] == second['id'])['tasks'][0]['id'], second_task['id'])
        self.assertIn(('missing_role', missing['id']), {(item['code'], item['source_id']) for item in data['warnings']})
        self.assertIn(('missing_tasks', missing['id']), {(item['code'], item['source_id']) for item in data['warnings']})
        self.assertEqual(self.outsider.get(self.base + '/uml').status_code, 403)

        edited = self.member.patch(self.base + f"/requirements/{first['id']}", json={
            'title': first['title'], 'description': first['description'], 'source': first['source'],
            'priority': first['priority'], 'acceptance_criteria': first['acceptance_criteria'],
            'story_role': '业务分析师', 'version': first['version'], 'reason': '确认实际故事角色',
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        refreshed = self.observer.get(self.base + '/uml').json()
        self.assertTrue(refreshed['use_case_stale'])
        self.assertEqual(self.member.post(self.base + '/uml/use-case/generate', json={
            'source_version': center.json()['source_version'],
        }).status_code, 409)
        regenerated = self.member.post(self.base + '/uml/use-case/generate', json={
            'source_version': refreshed['source_version'],
        })
        self.assertEqual(regenerated.status_code, 200, regenerated.text)
        self.assertEqual(regenerated.json()['version'], 2)
        self.assertIn('业务分析师', {item['name'] for item in regenerated.json()['content']['actors']})
        with connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM uml_generations WHERE diagram_type='use_case'").fetchone()[0], 2)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)

    def test_tc39_sequence_generation_uses_explicit_steps_and_preserves_last_valid_version(self):
        source = self.requirement('需求转任务', '产品负责人')
        accepted = self.requirement('任务验收', '项目管理员')
        source_task = self.task(source, '建立任务')
        accepted_task = self.task(accepted, '验收任务')
        first = self.member.post(self.base + '/uml/scenarios', json=self.scenario_body(
            '需求转任务', source_task['id'], accepted_task['id']))
        self.assertEqual(first.status_code, 201, first.text)
        first = first.json()
        second = self.member.post(self.base + '/uml/scenarios', json=self.scenario_body(
            '任务验收', accepted_task['id']))
        self.assertEqual(second.status_code, 201, second.text)
        for item in (first, second.json()):
            generated = self.member.post(self.base + f"/uml/scenarios/{item['id']}/generate", json={
                'scenario_version': item['version'],
            })
            self.assertEqual(generated.status_code, 200, generated.text)
            self.assertEqual([message['order'] for message in generated.json()['content']['messages']], [1, 2])
            self.assertTrue(all(message['task_id'].startswith('T-') for message in generated.json()['content']['messages']))
        current = self.observer.get(self.base + f"/uml/scenarios/{first['id']}").json()
        self.assertFalse(current['generation_stale'])
        self.assertEqual(current['latest_generation']['content']['messages'][1]['branch_condition'], '权限有效')

        invalid = self.scenario_body('需求转任务', source_task['id'])
        invalid['version'] = first['version']
        invalid['messages'][0]['from_participant'] = '不存在的参与者'
        rejected = self.member.patch(self.base + f"/uml/scenarios/{first['id']}", json=invalid)
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertIn('第1条消息', rejected.json()['detail'])
        missing_source = self.scenario_body('需求转任务', source_task['id'])
        missing_source['version'] = first['version']
        missing_source['messages'][0]['task_id'] = None
        self.assertEqual(self.member.patch(self.base + f"/uml/scenarios/{first['id']}", json=missing_source).status_code, 422)
        syntax_error = self.scenario_body('需求转任务', source_task['id'])
        syntax_error['version'] = first['version']
        syntax_error['messages'][0]['label'] = '非法\n换行'
        self.assertEqual(self.member.patch(self.base + f"/uml/scenarios/{first['id']}", json=syntax_error).status_code, 422)
        unchanged = self.observer.get(self.base + f"/uml/scenarios/{first['id']}").json()
        self.assertEqual(unchanged['version'], 1)
        self.assertEqual(unchanged['latest_generation']['version'], 1)

        valid = self.scenario_body('需求转任务', source_task['id'], accepted_task['id'])
        valid['version'] = first['version']
        valid['messages'][0]['label'] = '提交已确认需求'
        updated = self.member.patch(self.base + f"/uml/scenarios/{first['id']}", json=valid)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertTrue(updated.json()['generation_stale'])
        self.assertEqual(self.member.post(self.base + f"/uml/scenarios/{first['id']}/generate", json={
            'scenario_version': 1,
        }).status_code, 409)
        regenerated = self.member.post(self.base + f"/uml/scenarios/{first['id']}/generate", json={
            'scenario_version': updated.json()['version'],
        })
        self.assertEqual(regenerated.status_code, 200, regenerated.text)
        self.assertEqual(regenerated.json()['version'], 2)
        self.assertEqual(regenerated.json()['content']['messages'][0]['label'], '提交已确认需求')
        self.assertEqual(self.observer.post(self.base + f"/uml/scenarios/{first['id']}/generate", json={
            'scenario_version': 2,
        }).status_code, 403)
        self.assertEqual(self.outsider.get(f"/api/projects/2/uml/scenarios/{first['id']}").status_code, 404)


if __name__ == '__main__':
    unittest.main()
