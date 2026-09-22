import json
import os
import secrets
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect, migrate
from app.main import create_app
from app.security import hash_password


class Sprint6ModelHandler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        payload = json.loads(self.rfile.read(length))
        system = payload['messages'][0]['content']
        source = json.loads(payload['messages'][1]['content'])
        self.__class__.calls.append({'system': system, 'source': source})
        if 'risk_analysis' in system:
            owner_id = source['members'][0]['id']
            result = {
                'summary': '依据确定性指标生成风险应对建议，并单列缺失数据。',
                'risks': [{
                    'risk_id': item['risk_id'],
                    'severity': 'high' if item['metric_value'] > item['threshold'] * 1.5 else 'medium',
                    'recommendation': f"处理 {item['evidence']}",
                    'owner_id': item['owner_id'] or owner_id,
                    'next_check_date': '2026-10-27',
                } for item in source['evidence']['risks']],
            }
        elif 'quality_analysis' in system:
            result = {'summary': '三类资料均已按输入范围检查。', 'issues': []}
            labels = {'code': '代码可维护性', 'document': '文档完整性', 'test_report': '测试覆盖缺口'}
            for index, artifact in enumerate(source['artifacts'], start=1):
                result['issues'].append({
                    'issue_id': f'QUALITY-{index}', 'artifact_type': artifact['artifact_type'],
                    'file_name': artifact['file_name'], 'location': artifact['content_scope'],
                    'category': labels[artifact['artifact_type']],
                    'title': f"修复{labels[artifact['artifact_type']]}",
                    'evidence': artifact['content'].splitlines()[0].strip(),
                    'impact': '可能影响交付质量。', 'recommendation': '按证据补充并复验。',
                    'task_kind': 'defect' if artifact['artifact_type'] != 'document' else 'improvement',
                })
        else:
            evidence = source['evidence']
            if evidence['data_sufficient']:
                metric = next(item for item in evidence['metrics'] if item['key'] == 'average_cycle_hours')
                result = {'summary': '周期指标显示任务切分仍可优化。', 'bottlenecks': [{
                    'metric_key': metric['key'], 'metric_value': metric['value'],
                    'bottleneck': f"平均周期为 {metric['value']} 小时。",
                    'recommendation': '缩小批次并提前复核依赖。', 'action_title': '缩小任务批次',
                    'owner_id': source['members'][0]['id'], 'due_date': '2026-10-31',
                    'review_metric': '重新采集平均周期并与基线比较',
                }]}
            else:
                result = {'summary': evidence['data_notice'], 'bottlenecks': []}
        body = json.dumps({'choices': [{'message': {'content': json.dumps(result, ensure_ascii=False)}}]},
                          ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Sprint6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = hash_password(cls.password)
        cls.model_server = ThreadingHTTPServer(('127.0.0.1', 0), Sprint6ModelHandler)
        cls.model_thread = threading.Thread(target=cls.model_server.serve_forever, daemon=True)
        cls.model_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.model_server.shutdown()
        cls.model_server.server_close()
        cls.model_thread.join(timeout=2)

    def setUp(self):
        self.previous_env = {name: os.environ.get(name) for name in (
            'AIMANAGER_AI_ENDPOINT', 'AIMANAGER_AI_MODEL', 'AIMANAGER_AI_API_KEY')}
        os.environ['AIMANAGER_AI_ENDPOINT'] = (
            f'http://127.0.0.1:{self.model_server.server_port}/v1/chat/completions')
        os.environ['AIMANAGER_AI_MODEL'] = 'sprint6-test-model'
        os.environ['AIMANAGER_AI_API_KEY'] = 'server-only-test-key'
        Sprint6ModelHandler.calls.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        migrate(self.path)
        with connect(self.path) as db:
            for name in ('admin', 'member', 'observer'):
                db.execute('INSERT INTO users(username,name,password_hash) VALUES(?,?,?)',
                           (name, name, self.password_hash))
            db.execute('INSERT INTO projects(name) VALUES(?)', ('Sprint 6 测试项目',))
            db.executemany('INSERT INTO memberships(project_id,user_id,role,active) VALUES(?,?,?,1)', [
                (1, 1, 'admin'), (1, 2, 'member'), (1, 3, 'observer'),
            ])
        self.app = create_app(self.path)
        self.clients = []
        self.admin = self.login('admin')
        self.observer = self.login('observer')
        self.base = '/api/projects/1'

    def tearDown(self):
        for client in self.clients:
            client.__exit__(None, None, None)
        self.temp.cleanup()
        for name, value in self.previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def login(self, username):
        client = TestClient(self.app, headers={'X-Requested-With': 'aimanager'})
        client.__enter__()
        self.clients.append(client)
        response = client.post('/api/auth/login', json={
            'username': username, 'password': self.password,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def requirement(self, title='Sprint 6 来源需求'):
        response = self.admin.post(self.base + '/requirements', json={
            'title': title, 'description': '用于 Sprint 6 自动化验证', 'source': '测试基线',
            'priority': 'Must', 'acceptance_criteria': '分析结果可追溯', 'story_role': '质量负责人',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def task(self, requirement, title, due_date='2026-10-10'):
        response = self.admin.post(self.base + '/tasks', json={
            'title': title, 'requirement_id': requirement['id'], 'owner_id': 2,
            'due_date': due_date, 'sprint': 'S6',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def capacity(self, hours=20):
        response = self.admin.patch(self.base + '/members/2/capacity', json={
            'weekly_capacity_hours': hours, 'available_from': '2026-09-01',
            'available_to': '2026-12-31', 'skill_tags': ['后端'], 'version': 0,
            'reason': 'Sprint 6 风险测试',
        })
        self.assertEqual(response.status_code, 200, response.text)

    def plan(self, task, remaining=60):
        response = self.admin.patch(self.base + f"/tasks/{task['id']}/plan", json={
            'estimated_hours': remaining, 'actual_hours': 0, 'remaining_hours': remaining,
            'planned_start': '2026-10-01', 'planned_end': '2026-10-31',
            'plan_locked': False, 'required_skills': ['后端'], 'version': task['version'],
            'reason': 'Sprint 6 测试计划',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def apply(self, run, reason='人工核对证据后采纳'):
        response = self.admin.post(self.base + f"/ai/runs/{run['id']}/apply", json={
            'version': run['version'], 'reason': reason,
            'operation_id': secrets.token_urlsafe(18),
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_tc44_risk_rules_threshold_history_actions_and_manual_close(self):
        requirement = self.requirement()
        task = self.plan(self.task(requirement, '延期并阻塞的任务'))
        self.capacity()
        response = self.admin.patch(self.base + f"/tasks/{task['id']}/blocker", json={
            'blocked': True, 'reason': '等待外部接口', 'version': task['version'],
        })
        self.assertEqual(response.status_code, 200, response.text)
        with connect(self.path) as db:
            db.execute('''INSERT INTO events(project_id,entity_type,entity_id,event_type,actor_id,
                occurred_at,before_json,after_json,reason,operation_id) VALUES(1,'task',?,'blocked',1,
                '2026-10-01T01:00:00+00:00',NULL,?,?,?)''',
                (task['id'], json.dumps({'status': task['status']}, ensure_ascii=False),
                 '历史阻塞样本', secrets.token_urlsafe(24)))

        self.assertEqual(self.observer.post(self.base + '/ai/risks', json={}).status_code, 403)
        response = self.admin.post(self.base + '/ai/risks', json={
            'as_of_date': '2026-10-24', 'overload_percent': 100,
            'blocked_workdays': 1, 'threshold_reason': '',
        })
        self.assertEqual(response.status_code, 201, response.text)
        run = response.json()
        risk_types = {item['type'] for item in run['output']['evidence']['risks']}
        self.assertTrue({'overload', 'blocked', 'overdue', 'forecast_late'}.issubset(risk_types))
        self.assertEqual(len(run['output']['analysis']['risks']),
                         len(run['output']['evidence']['risks']))
        applied = self.apply(run)
        self.assertEqual(applied['status'], 'applied')
        center = self.admin.get(self.base + '/ai').json()
        self.assertEqual(len(center['actions']), len(run['output']['evidence']['risks']))
        self.assertEqual(center['risk_threshold_history'][0]['version'], 1)

        action = center['actions'][0]
        response = self.admin.patch(self.base + f"/ai/actions/{action['id']}", json={
            'status': '已完成', 'version': action['version'],
            'current_metric_value': action['baseline_metric_value'], 'review_note': '指标未改善',
        })
        self.assertEqual(response.status_code, 409)
        response = self.admin.patch(self.base + f"/ai/actions/{action['id']}", json={
            'status': '已完成', 'version': action['version'],
            'current_metric_value': max(0, action['baseline_metric_value'] - 0.5),
            'review_note': '重新采集指标并人工复核，数值已经改善',
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], '已完成')

        response = self.admin.post(self.base + '/ai/risks', json={
            'as_of_date': '2026-10-24', 'overload_percent': 120,
            'blocked_workdays': 1, 'threshold_reason': '',
        })
        self.assertEqual(response.status_code, 422)

    def test_tc45_quality_uses_three_traceable_inputs_and_creates_tasks_only_after_review(self):
        requirement = self.requirement('质量问题承接需求')
        artifacts = [
            {'artifact_type': 'code', 'file_name': 'service.py', 'version': 'abc123',
             'content_scope': '10-18行', 'content': 'except Exception: pass\nreturn result'},
            {'artifact_type': 'document', 'file_name': 'README.md', 'version': 'v2',
             'content_scope': '运行说明', 'content': '启动服务后访问页面。\n未说明环境变量。'},
            {'artifact_type': 'test_report', 'file_name': 'report.txt', 'version': 'run-7',
             'content_scope': '失败与覆盖', 'content': 'FAILED test_timeout\ncoverage 61%'},
        ]
        response = self.admin.post(self.base + '/ai/quality-analyses', json={
            'target_requirement_id': requirement['id'], 'owner_id': 2,
            'due_date': '2026-10-31', 'artifacts': artifacts,
        })
        self.assertEqual(response.status_code, 201, response.text)
        run = response.json()
        self.assertEqual(len(run['output']['analysis']['issues']), 3)
        before = self.admin.get(self.base + '/tasks').json()
        self.assertEqual(before, [])
        self.apply(run)
        after = self.admin.get(self.base + '/tasks').json()
        self.assertEqual(len(after), 3)
        self.assertTrue(all(item['sprint'] == 'S6' for item in after))
        self.assertTrue(all('AI质量分析经人工核实' in item['description'] for item in after))

        response = self.admin.post(self.base + '/ai/quality-analyses', json={
            'target_requirement_id': requirement['id'], 'owner_id': 2,
            'artifacts': artifacts[:2],
        })
        self.assertEqual(response.status_code, 422)

    def test_tc46_efficiency_requires_sufficient_records_and_creates_comparable_action(self):
        requirement = self.requirement('效率分析来源')
        self.capacity(40)
        for index in range(3):
            task = self.task(requirement, f'已完成任务 {index + 1}', None)
            for status, accepted in (('进行中', False), ('待验收', False), ('已完成', True)):
                response = self.admin.patch(self.base + f"/tasks/{task['id']}/status", json={
                    'status': status, 'version': task['version'], 'reason': '效率样本',
                    'acceptance_confirmed': accepted,
                })
                self.assertEqual(response.status_code, 200, response.text)
                task = response.json()
            with connect(self.path) as db:
                db.execute("UPDATE tasks SET created_at=? WHERE project_id=1 AND pk=?",
                           (f'2026-10-0{1 + index}T01:00:00+00:00', int(task['id'].split('-')[1])))
                for event_type, status, day in (
                        ('status_changed', '进行中', 2 + index),
                        ('accepted', '已完成', 4 + index)):
                    db.execute('''INSERT INTO events(project_id,entity_type,entity_id,event_type,actor_id,
                        occurred_at,before_json,after_json,reason,operation_id)
                        VALUES(1,'task',?,?,1,?,NULL,?,?,?)''',
                        (task['id'], event_type, f'2026-10-0{day}T01:00:00+00:00',
                         json.dumps({'status': status}, ensure_ascii=False),
                         '历史效率样本', secrets.token_urlsafe(24)))

        response = self.admin.post(self.base + '/ai/efficiency-analyses', json={
            'as_of_date': '2026-10-24',
        })
        self.assertEqual(response.status_code, 201, response.text)
        run = response.json()
        evidence = run['output']['evidence']
        self.assertTrue(evidence['data_sufficient'])
        self.assertEqual(len(evidence['task_records']), 3)
        self.assertIn('不用于评价个人绩效', evidence['interpretation_rule'])
        self.assertEqual(len(run['output']['analysis']['bottlenecks']), 1)
        self.apply(run)
        actions = self.admin.get(self.base + '/ai').json()['actions']
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['source_kind'], 'efficiency')
        self.assertEqual(actions[0]['baseline_metric_key'], 'average_cycle_hours')


if __name__ == '__main__':
    unittest.main()
