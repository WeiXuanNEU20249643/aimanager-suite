import json
import os
import secrets
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect, migrate
from app.main import create_app
from app.security import hash_password


class ModelHandler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        payload = json.loads(self.rfile.read(length))
        system = payload['messages'][0]['content']
        source = json.loads(payload['messages'][1]['content'])
        self.__class__.calls.append({'path': self.path, 'authorization': self.headers.get('Authorization'),
                                     'model': payload.get('model'), 'system': system, 'source': source})
        serialized = json.dumps(source, ensure_ascii=False)
        if '触发超时' in serialized:
            time.sleep(0.4)
        if '触发限额' in serialized:
            self.send_json(429, {'error': {'message': 'quota'}})
            return
        if '触发格式异常' in serialized:
            self.send_json(200, {'choices': [{'message': {'content': 'not-json'}}]})
            return
        if 'prd_breakdown' in system:
            prd = source['prd_text']
            first_paragraph = next(part.strip() for part in prd.split('\n') if part.strip())
            result = {'stories': [{
                'local_id': 'STORY-1', 'role': '产品负责人', 'story': '建立发布审批',
                'acceptance_criteria': ['给定待发布版本，审批通过后允许发布'],
                'source_paragraph': first_paragraph, 'priority': 'Must',
                'tasks': [
                    {'local_id': 'TASK-1', 'title': '实现审批接口', 'description': '保存审批决定',
                     'estimate_hours': 8, 'required_skills': ['后端'], 'depends_on': []},
                    {'local_id': 'TASK-2', 'title': '实现审批页面', 'description': '展示审批状态',
                     'estimate_hours': 6, 'required_skills': ['前端'], 'depends_on': ['TASK-1']},
                ],
            }, {
                'local_id': 'STORY-2', 'role': '审计员', 'story': '查看虚构来源',
                'acceptance_criteria': ['可以查看'], 'source_paragraph': '原文中不存在的段落',
                'priority': 'Should', 'tasks': [{'local_id': 'TASK-3', 'title': '虚构任务',
                    'description': '', 'estimate_hours': 2, 'required_skills': [], 'depends_on': []}],
            }], 'ambiguous_items': ['审批超时时间尚未明确'] if '歧义' in prd else [],
                'unsupported_items': []}
        elif 'progress_forecast' in system:
            evidence = source['evidence']
            result = {'summary': f"预计完成日期为 {evidence['expected_completion_date'] or '无法计算'}",
                      'factors': [f"使用 {evidence['sample_count']} 条实际记录",
                                  f"校准系数 {evidence['median_actual_estimate_ratio']}"],
                      'confidence_limits': [evidence['data_notice']] if evidence['data_notice'] else []}
        else:
            plan = source['plan']
            result = {'summary': '建议遵循依赖、技能与容量约束，不承诺全局最优',
                      'assignments': [{'task_id': item['task_id'],
                                       'reason': f"由 {item['after_owner_name']} 按容量承接",
                                       'tradeoffs': ['优先保留锁定任务', '按依赖顺序开始']}
                                      for item in plan['proposals']]}
        self.send_json(200, {'choices': [{'message': {'content': json.dumps(result, ensure_ascii=False)}}]})


class Sprint5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = hash_password(cls.password)
        cls.model_server = ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
        cls.model_thread = threading.Thread(target=cls.model_server.serve_forever, daemon=True)
        cls.model_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.model_server.shutdown()
        cls.model_server.server_close()
        cls.model_thread.join(timeout=2)

    def setUp(self):
        self.previous_env = {name: os.environ.get(name) for name in (
            'AIMANAGER_AI_ENDPOINT', 'AIMANAGER_AI_MODEL', 'AIMANAGER_AI_API_KEY',
            'AIMANAGER_AI_TIMEOUT_SECONDS')}
        os.environ['AIMANAGER_AI_ENDPOINT'] = f'http://127.0.0.1:{self.model_server.server_port}/v1/chat/completions'
        os.environ['AIMANAGER_AI_MODEL'] = 'test-structured-model'
        self.api_key = secrets.token_urlsafe(24)
        os.environ['AIMANAGER_AI_API_KEY'] = self.api_key
        os.environ['AIMANAGER_AI_TIMEOUT_SECONDS'] = '0.15'
        ModelHandler.calls.clear()
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
        for name, value in self.previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def login(self, username):
        client = TestClient(self.app, headers={'X-Requested-With': 'aimanager'})
        client.__enter__()
        self.clients.append(client)
        response = client.post('/api/auth/login', json={'username': username, 'password': self.password})
        self.assertEqual(response.status_code, 200, response.text)
        return client

    def requirement(self, title='测试需求'):
        response = self.admin.post(self.base + '/requirements', json={
            'title': title, 'description': '用于 Sprint 5 验证', 'source': '自动化测试',
            'priority': 'Must', 'acceptance_criteria': '结果可复算', 'story_role': '项目经理',
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def task(self, requirement, title, owner_id=2, sprint='S5'):
        response = self.admin.post(self.base + '/tasks', json={
            'title': title, 'requirement_id': requirement['id'], 'owner_id': owner_id, 'sprint': sprint,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def plan(self, task, estimated, actual, remaining, skills=None, locked=False,
             start=None, end=None):
        response = self.admin.patch(self.base + f"/tasks/{task['id']}/plan", json={
            'estimated_hours': estimated, 'actual_hours': actual, 'remaining_hours': remaining,
            'planned_start': start, 'planned_end': end, 'plan_locked': locked,
            'required_skills': skills or [], 'version': task['version'], 'reason': 'Sprint 5 测试',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def complete(self, task):
        for status in ('进行中', '待验收'):
            response = self.admin.patch(self.base + f"/tasks/{task['id']}/status", json={
                'status': status, 'version': task['version'], 'reason': '', 'acceptance_confirmed': False,
            })
            self.assertEqual(response.status_code, 200, response.text)
            task = response.json()
        response = self.admin.patch(self.base + f"/tasks/{task['id']}/status", json={
            'status': '已完成', 'version': task['version'], 'reason': '', 'acceptance_confirmed': True,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def capacity(self, user_id, hours, skills, version=0):
        response = self.admin.patch(self.base + f'/members/{user_id}/capacity', json={
            'weekly_capacity_hours': hours, 'available_from': '2026-10-01',
            'available_to': '2026-12-31', 'skill_tags': skills, 'version': version,
            'reason': 'Sprint 5 测试容量',
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_tc41_tc47_real_call_review_idempotency_failures_and_project_scope(self):
        prd = '发布前必须由产品负责人审批。\n歧义：审批超时时间待确认。'
        self.assertEqual(self.observer.post(self.base + '/ai/prd-breakdowns', json={
            'source_name': '发布 PRD', 'prd_text': prd,
        }).status_code, 403)
        response = self.member.post(self.base + '/ai/prd-breakdowns', json={
            'source_name': '发布 PRD', 'prd_text': prd,
        })
        self.assertEqual(response.status_code, 201, response.text)
        run = response.json()
        self.assertEqual(run['status'], 'draft')
        self.assertEqual(len(run['output']['stories']), 1)
        self.assertEqual(len(run['output']['unsupported_items']), 1)
        self.assertEqual(run['output']['ambiguous_items'], ['审批超时时间尚未明确'])
        self.assertEqual(ModelHandler.calls[-1]['authorization'], 'Bearer ' + self.api_key)
        self.assertEqual(ModelHandler.calls[-1]['model'], 'test-structured-model')
        self.assertNotIn(self.api_key, response.text)
        self.assertEqual(self.outsider.get('/api/projects/2/ai/runs/' + str(run['id'])).status_code, 404)

        edited = run['output']
        edited['stories'][0]['story'] = '建立可追溯发布审批'
        response = self.member.patch(self.base + f"/ai/runs/{run['id']}", json={
            'version': run['version'], 'output': edited, 'reason': '补充可追溯性',
        })
        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()
        before_counts = self._business_counts()
        operation_id = 'apply-release-prd-001'
        applied = self.member.post(self.base + f"/ai/runs/{run['id']}/apply", json={
            'version': run['version'], 'reason': '确认来源和验收条件', 'operation_id': operation_id,
        })
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()['status'], 'applied')
        after_counts = self._business_counts()
        self.assertEqual(after_counts[0] - before_counts[0], 1)
        self.assertEqual(after_counts[1] - before_counts[1], 2)
        self.assertEqual(after_counts[2] - before_counts[2], 1)
        repeated = self.member.post(self.base + f"/ai/runs/{run['id']}/apply", json={
            'version': run['version'], 'reason': '网络重试', 'operation_id': operation_id,
        })
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(self._business_counts(), after_counts)

        rejected = self.member.post(self.base + '/ai/prd-breakdowns', json={
            'source_name': '拒绝样例', 'prd_text': '仅用于验证否决不写入。',
        }).json()
        counts = self._business_counts()
        response = self.member.post(self.base + f"/ai/runs/{rejected['id']}/reject", json={
            'version': rejected['version'], 'reason': '业务价值不足',
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'rejected')
        self.assertEqual(self._business_counts()[:3], counts[:3])

        stale = self.member.post(self.base + '/ai/prd-breakdowns', json={
            'source_name': '版本冲突', 'prd_text': '需求需要审批。',
        }).json()
        self.requirement('并发新增需求')
        self.assertEqual(self.member.post(self.base + f"/ai/runs/{stale['id']}/apply", json={
            'version': stale['version'], 'reason': '尝试应用旧版', 'operation_id': 'stale-apply-001',
        }).status_code, 409)

        business_before_failures = self._business_counts()[:3]
        for source, expected, code in [('触发格式异常', 502, 'invalid_format'),
                                       ('触发限额', 429, 'quota_limited'),
                                       ('触发超时', 504, 'timeout')]:
            failed = self.member.post(self.base + '/ai/prd-breakdowns', json={
                'source_name': source, 'prd_text': source,
            })
            self.assertEqual(failed.status_code, expected, failed.text)
            self.assertEqual(failed.json()['status'], 'failed')
            self.assertEqual(failed.json()['error_code'], code)
        self.assertEqual(self._business_counts()[:3], business_before_failures)
        with connect(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ai_reviews WHERE action='applied'").fetchone()[0], 1)

    def test_tc42_forecast_uses_median_and_marks_insufficient_history(self):
        requirement = self.requirement('进度预测来源')
        active = self.plan(self.task(requirement, '剩余任务'), 10, 0, 10)
        self.capacity(2, 40, ['后端'])
        baseline = self.member.post(self.base + '/ai/forecasts', json={'as_of_date': '2026-10-12'})
        self.assertEqual(baseline.status_code, 201, baseline.text)
        evidence = baseline.json()['output']['evidence']
        self.assertFalse(evidence['calibration_applied'])
        self.assertIn('历史不足3条', evidence['data_notice'])

        for index, (estimated, actual) in enumerate(((8, 8), (10, 15), (20, 30)), start=1):
            item = self.task(requirement, f'历史任务 {index}')
            item = self.plan(item, estimated, actual, 0)
            self.complete(item)
        forecast = self.member.post(self.base + '/ai/forecasts', json={'as_of_date': '2026-10-12'})
        self.assertEqual(forecast.status_code, 201, forecast.text)
        run = forecast.json()
        evidence = run['output']['evidence']
        self.assertTrue(evidence['calibration_applied'])
        self.assertEqual(evidence['sample_count'], 3)
        self.assertEqual(evidence['median_actual_estimate_ratio'], 1.5)
        calculation = next(item for item in evidence['tasks'] if item['task_id'] == active['id'])
        self.assertEqual(calculation['calibrated_remaining_hours'], 15)
        self.assertIsNotNone(evidence['expected_completion_date'])
        task_before = self.admin.get(self.base + f"/tasks/{active['id']}").json()
        applied = self.member.post(self.base + f"/ai/runs/{run['id']}/apply", json={
            'version': run['version'], 'reason': '确认预测依据', 'operation_id': 'forecast-apply-001',
        })
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(self.admin.get(self.base + f"/tasks/{active['id']}").json(), task_before)

        explanation_failure = self.task(requirement, '触发格式异常')
        explanation_failure = self.plan(explanation_failure, 4, 4, 0)
        self.complete(explanation_failure)
        failed = self.member.post(self.base + '/ai/forecasts', json={'as_of_date': '2026-10-12'})
        self.assertEqual(failed.status_code, 502, failed.text)
        self.assertEqual(failed.json()['status'], 'failed')
        self.assertEqual(failed.json()['error_code'], 'invalid_format')

    def test_tc43_schedule_checks_skills_dependencies_capacity_and_locked_work(self):
        requirement = self.requirement('智能排期来源')
        self.capacity(1, 20, ['产品'])
        self.capacity(2, 40, ['后端', '前端'])
        first = self.plan(self.task(requirement, '后端基础'), 8, 0, 8, ['后端'])
        second = self.plan(self.task(requirement, '前端接入'), 8, 0, 8, ['前端'])
        dependency = self.admin.post(self.base + f"/tasks/{second['id']}/dependencies", json={
            'depends_on_id': first['id'], 'reason': '先有服务端接口',
        })
        self.assertEqual(dependency.status_code, 201, dependency.text)
        second = dependency.json()
        locked = self.plan(self.task(requirement, '锁定承诺'), 8, 0, 8, ['后端'], True,
                           '2026-10-12', '2026-10-13')

        generated = self.member.post(self.base + '/ai/schedules', json={'start_date': '2026-10-12'})
        self.assertEqual(generated.status_code, 201, generated.text)
        run = generated.json()
        plan = run['output']['plan']
        self.assertFalse(plan['blocked'])
        proposals = {item['task_id']: item for item in plan['proposals']}
        self.assertEqual(proposals[first['id']]['after_owner_id'], 2)
        self.assertGreater(proposals[second['id']]['after_start'], proposals[first['id']]['after_end'])
        self.assertIn(locked['id'], {item['task_id'] for item in plan['preserved']})
        locked_before = self.admin.get(self.base + f"/tasks/{locked['id']}").json()
        response = self.member.post(self.base + f"/ai/runs/{run['id']}/apply", json={
            'version': run['version'], 'reason': '约束和差异已核对', 'operation_id': 'schedule-apply-001',
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.admin.get(self.base + f"/tasks/{locked['id']}").json(), locked_before)
        applied_second = self.admin.get(self.base + f"/tasks/{second['id']}").json()
        self.assertEqual(applied_second['planned_start'], proposals[second['id']]['after_start'])

        impossible = self.plan(self.task(requirement, '稀缺技能任务'), 8, 0, 8, ['量子编译'])
        blocked = self.member.post(self.base + '/ai/schedules', json={'start_date': '2026-10-12'})
        self.assertEqual(blocked.status_code, 201, blocked.text)
        blocked_run = blocked.json()
        self.assertTrue(blocked_run['output']['plan']['blocked'])
        self.assertIn('skill_or_capacity_missing', {item['type'] for item in blocked_run['output']['plan']['conflicts']})
        before = self.admin.get(self.base + f"/tasks/{impossible['id']}").json()
        rejected_apply = self.member.post(self.base + f"/ai/runs/{blocked_run['id']}/apply", json={
            'version': blocked_run['version'], 'reason': '尝试应用冲突方案',
            'operation_id': 'blocked-schedule-001',
        })
        self.assertEqual(rejected_apply.status_code, 409, rejected_apply.text)
        self.assertEqual(self.admin.get(self.base + f"/tasks/{impossible['id']}").json(), before)

    def _business_counts(self):
        with connect(self.path) as db:
            return (db.execute('SELECT COUNT(*) FROM requirements WHERE project_id=1').fetchone()[0],
                    db.execute('SELECT COUNT(*) FROM tasks WHERE project_id=1').fetchone()[0],
                    db.execute('SELECT COUNT(*) FROM task_dependencies WHERE project_id=1').fetchone()[0],
                    db.execute('SELECT COUNT(*) FROM events WHERE project_id=1').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
