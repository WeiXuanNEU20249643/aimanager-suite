import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import connect, migrate
from .schemas import (
    AIEfficiencyIn, AIForecastIn, AIOutputEditIn, AIPRDBreakdownIn, AIQualityIn,
    AIReviewIn, AIRiskIn, AIScheduleIn,
    BlockerIn, CapacityIn, CustomRoleEdit, CustomRoleIn, DependencyIn, DependencyRemoveIn,
    ImprovementActionEditIn, LoginIn, MemberIn, MilestoneEdit, MilestoneIn, RequirementEdit, RequirementIn,
    ReplanIn, RoleIn, SequenceGenerateIn, SequenceScenarioEdit, SequenceScenarioIn,
    StatusIn, TaskActionIn, TaskEdit, TaskIn, TaskPlanIn, TaskSourceIn, UseCaseGenerateIn,
)
from .ai import (
    AIServiceError, ai_settings, breakdown_prompt, call_structured, forecast_calculation,
    efficiency_calculation, efficiency_prompt, forecast_prompt, latest_risk_thresholds,
    list_risk_thresholds, list_runs as list_ai_runs, load_run as load_ai_run, normalize_breakdown,
    public_ai_settings, public_provider_url, quality_prompt, risk_calculation, risk_prompt,
    save_run as save_ai_run, schedule_calculation, schedule_prompt, validate_efficiency_analysis,
    validate_forecast_explanation, validate_quality_analysis, validate_review_output,
    validate_risk_analysis, validate_schedule_explanation,
)
from .planning import (
    calculate_replan, plan_state, planning_impact, planning_snapshot, touch_plan_state,
)
from .security import hash_password, token_hash, verify_password
from .uml import build_sequence, build_use_case, latest_generation, save_generation, scenario, scenarios

COOKIE = 'aimanager_session'
SESSION_SECONDS = 12 * 60 * 60
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))

PERMISSIONS = (
    'requirement.read', 'requirement.write', 'requirement.history',
    'task.read', 'task.write', 'comment.read', 'comment.write',
    'milestone.read', 'milestone.write', 'statistics.read', 'history.read',
    'uml.read', 'uml.write', 'ai.read', 'ai.write', 'ai.apply',
)
BUILTIN_PERMISSIONS = {
    'admin': set(PERMISSIONS),
    'member': set(PERMISSIONS) - {'milestone.write'},
    'observer': {'requirement.read', 'requirement.history', 'task.read',
                 'comment.read', 'milestone.read', 'statistics.read', 'history.read', 'uml.read', 'ai.read'},
}


def now():
    return datetime.now(timezone.utc).isoformat()


def current_natural_week():
    # China Standard Time is fixed at UTC+08:00 and has no daylight-saving transitions.
    local_now = datetime.now(timezone(timedelta(hours=8), name='Asia/Shanghai'))
    start = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return start, end


def fail(status, message):
    raise HTTPException(status, message)


def event(db, project_id, kind, entity_id, action, actor, before, after, reason='', touch_plan=True):
    db.execute('INSERT INTO events(project_id,entity_type,entity_id,event_type,actor_id,occurred_at,before_json,after_json,reason,operation_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
               (project_id, kind, entity_id, action, actor, now(),
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False), reason, str(uuid.uuid4())))
    if touch_plan and kind in {'task', 'task_dependency', 'member_capacity', 'membership', 'requirement'}:
        touch_plan_state(db, project_id, actor, now())


def key(value, prefix):
    if not re.fullmatch(prefix + r'-[0-9]{3,19}', value):
        fail(404, '记录不存在')
    number = int(value.split('-')[1])
    if number > 9223372036854775807 or value != f'{prefix}-{number:03d}':
        fail(404, '记录不存在')
    return number


def requirement(db, project_id, req_id):
    r = db.execute('SELECT r.*,u.name creator_name FROM requirements r JOIN users u ON u.id=r.created_by WHERE r.project_id=? AND r.pk=?', (project_id, key(req_id, 'REQ'))).fetchone()
    if not r:
        fail(404, '需求不存在')
    result = dict(r)
    result['id'] = f"REQ-{result.pop('pk'):03d}"
    result['priority'] = result.get('priority') or 'Must'
    result['acceptance_criteria'] = result.get('acceptance_criteria') or '待补充验收条件'
    result['story_role'] = result.get('story_role') or ''
    return result


def task(db, project_id, task_id):
    row = db.execute('''SELECT t.*,u.name owner_name,c.name creator_name,ms.name milestone_name,
        cb.name cancelled_by_name,
        COALESCE(m.active,0) AS owner_active FROM tasks t
        LEFT JOIN users u ON u.id=t.owner_id
        LEFT JOIN memberships m ON m.user_id=t.owner_id AND m.project_id=t.project_id
        LEFT JOIN milestones ms ON ms.id=t.milestone_id AND ms.project_id=t.project_id
        LEFT JOIN users cb ON cb.id=t.cancelled_by
        JOIN users c ON c.id=t.created_by WHERE t.project_id=? AND t.pk=?''',
        (project_id, key(task_id, 'T'))).fetchone()
    if not row:
        fail(404, '任务不存在')
    result = dict(row)
    result['id'] = f"T-{result.pop('pk'):03d}"
    result['requirement_id'] = f"REQ-{result.pop('requirement_pk'):03d}"
    result['owner_active'] = bool(result['owner_active'])
    result['review_required'] = bool(result.get('review_required'))
    result['cancelled'] = bool(result.get('cancelled_at'))
    result['plan_locked'] = bool(result.get('plan_locked'))
    result['manually_blocked'] = bool(result.get('manual_block_reason'))
    result['required_skills'] = json.loads(result.pop('required_skills_json') or '[]')
    dependencies = [dict(r) for r in db.execute('''SELECT d.depends_on_pk,t.title,t.status,t.cancelled_at,d.reason,u.name actor_name,d.created_at
        FROM task_dependencies d JOIN tasks t ON t.project_id=d.project_id AND t.pk=d.depends_on_pk
        JOIN users u ON u.id=d.created_by WHERE d.project_id=? AND d.task_pk=? ORDER BY d.created_at,d.depends_on_pk''',
        (project_id, key(task_id, 'T')))]
    for dependency in dependencies:
        dependency['id'] = f"T-{dependency.pop('depends_on_pk'):03d}"
        dependency['cancelled'] = bool(dependency['cancelled_at'])
        dependency['complete'] = dependency['status'] == '已完成' and not dependency['cancelled']
    result['dependencies'] = dependencies
    result['dependency_blocked'] = any(not item['complete'] for item in dependencies)
    return result


def require_mutable_task(item):
    if item['cancelled']:
        fail(409, '已取消任务不可继续编辑或流转')


def capacity(db, project_id, user_id):
    row = db.execute('''SELECT mc.*,u.name updated_by_name FROM member_capacities mc
        JOIN users u ON u.id=mc.updated_by WHERE mc.project_id=? AND mc.user_id=?''',
        (project_id, user_id)).fetchone()
    if not row:
        return {'weekly_capacity_hours': None, 'available_from': None, 'available_to': None,
                'skill_tags': [], 'capacity_version': 0, 'capacity_updated_at': None,
                'capacity_updated_by_name': None}
    result = dict(row)
    return {'weekly_capacity_hours': result['weekly_capacity_hours'],
            'available_from': result['available_from'], 'available_to': result['available_to'],
            'skill_tags': json.loads(result['skill_tags_json']), 'capacity_version': result['version'],
            'capacity_updated_at': result['updated_at'],
            'capacity_updated_by_name': result['updated_by_name']}


def check_owner(db, project_id, owner_id):
    if owner_id is not None and not db.execute('SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id WHERE project_id=? AND user_id=? AND m.active=1 AND u.active=1', (project_id, owner_id)).fetchone():
        fail(422, '负责人必须是有效项目成员')


def check_milestone(db, project_id, milestone_id):
    if milestone_id is not None and not db.execute('SELECT 1 FROM milestones WHERE project_id=? AND id=?', (project_id, milestone_id)).fetchone():
        fail(422, '里程碑必须属于当前项目')


def custom_permissions(db, role_id):
    return {row['permission'] for row in db.execute('SELECT permission FROM role_permissions WHERE role_id=?', (role_id,))}


def member_access(db, project_id, actor):
    row = db.execute('''SELECT m.role,m.custom_role_id,cr.name custom_role_name
        FROM memberships m LEFT JOIN custom_roles cr ON cr.id=m.custom_role_id AND cr.project_id=m.project_id
        WHERE m.project_id=? AND m.user_id=? AND m.active=1''', (project_id, actor['id'])).fetchone()
    if not row:
        fail(403, '没有此项目的访问权限')
    if row['custom_role_id']:
        if not row['custom_role_name']:
            fail(403, '项目角色配置无效')
        return {**actor, 'role': 'custom', 'role_id': row['custom_role_id'],
                'role_name': row['custom_role_name'], 'permissions': custom_permissions(db, row['custom_role_id'])}
    return {**actor, 'role': row['role'], 'role_id': None,
            'role_name': {'admin': '管理员', 'member': '成员', 'observer': '观察者'}[row['role']],
            'permissions': BUILTIN_PERMISSIONS[row['role']]}


def public_access(actor):
    return {k: (sorted(v) if k == 'permissions' else v) for k, v in actor.items()}


def parse_role(db, project_id, value):
    if value in BUILTIN_PERMISSIONS:
        return value, None
    match = re.fullmatch(r'custom:(\d+)', value)
    if not match:
        fail(422, '角色不存在或不属于当前项目')
    role_id = int(match.group(1))
    if not db.execute('SELECT 1 FROM custom_roles WHERE project_id=? AND id=?', (project_id, role_id)).fetchone():
        fail(422, '角色不存在或不属于当前项目')
    return 'member', role_id


def validate_permissions(values):
    permissions = set(values)
    if len(values) != len(permissions) or not permissions.issubset(PERMISSIONS):
        fail(422, '权限配置包含无效或重复项目')
    for permission in permissions:
        if permission.endswith('.write') and permission.replace('.write', '.read') not in permissions:
            fail(422, '写权限必须同时包含对应读取权限')
    if 'requirement.history' in permissions and 'requirement.read' not in permissions:
        fail(422, '查看需求版本必须同时包含需求读取权限')
    return permissions


def milestone(db, project_id, milestone_id):
    row = db.execute('''SELECT ms.*,u.name creator_name FROM milestones ms JOIN users u ON u.id=ms.created_by
        WHERE ms.project_id=? AND ms.id=?''', (project_id, milestone_id)).fetchone()
    if not row:
        fail(404, '里程碑不存在')
    result = dict(row)
    counts = db.execute('''SELECT COUNT(*) total,
        SUM(CASE WHEN status='已完成' THEN 1 ELSE 0 END) completed
        FROM tasks WHERE project_id=? AND milestone_id=? AND cancelled_at IS NULL''', (project_id, milestone_id)).fetchone()
    result['active_count'] = counts['total']
    result['completed_count'] = counts['completed'] or 0
    result['completion_rate'] = round(result['completed_count'] * 100 / result['active_count'], 1) if result['active_count'] else None
    return result


def plan_runs(db, project_id, requirement_pk, limit=10):
    rows = db.execute('''SELECT pr.*,u.name triggered_by_name FROM plan_runs pr
        JOIN users u ON u.id=pr.triggered_by
        WHERE pr.project_id=? AND pr.requirement_pk=? ORDER BY pr.id DESC LIMIT ?''',
        (project_id, requirement_pk, limit)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['changes'] = json.loads(item.pop('changes_json'))
        item['conflicts'] = json.loads(item.pop('conflicts_json'))
        item['requirement_id'] = f"REQ-{item.pop('requirement_pk'):03d}"
        item['applied'] = item['status'] == 'applied'
        result.append(item)
    return result


def improvement_action(db, project_id, action_id):
    row = db.execute('''SELECT ia.*,owner.name owner_name,creator.name created_by_name,
        updater.name updated_by_name FROM improvement_actions ia
        JOIN users owner ON owner.id=ia.owner_id
        JOIN users creator ON creator.id=ia.created_by
        JOIN users updater ON updater.id=ia.updated_by
        WHERE ia.project_id=? AND ia.id=?''', (project_id, action_id)).fetchone()
    if not row:
        fail(404, '改进行动不存在')
    return dict(row)


def improvement_actions(db, project_id):
    rows = db.execute('''SELECT id FROM improvement_actions WHERE project_id=?
        ORDER BY CASE status WHEN '进行中' THEN 0 WHEN '待处理' THEN 1 ELSE 2 END,id DESC''',
        (project_id,)).fetchall()
    return [improvement_action(db, project_id, row['id']) for row in rows]


def ai_members(db, project_id):
    return [dict(row) for row in db.execute('''SELECT u.id,u.name,m.role FROM memberships m
        JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND m.active=1 AND u.active=1
        AND m.role<>'observer' ORDER BY u.id''', (project_id,))]


def create_app(db_path=None):
    @asynccontextmanager
    async def lifespan(app):
        migrate(db_path)
        yield

    app = FastAPI(title='爱管理 API', version='6.0.0', lifespan=lifespan)

    @app.middleware('http')
    async def request_guard(request, call_next):
        # Same-origin fetch sets this non-simple header; no cross-origin CORS grants.
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('X-Requested-With') != 'aimanager':
            return JSONResponse({'detail': '请求校验失败'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never reflect submitted passwords or other input values.
        return JSONResponse({'detail': '输入不合法，请检查必填字段、日期和选项',
                             'fields': ['.'.join(map(str, e['loc'][1:])) for e in exc.errors()]}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, exc):
        return JSONResponse({'detail': '保存或读取失败，请稍后重试'}, status_code=503)

    def database():
        db = connect(db_path)
        try:
            # Authorization and writes share a transaction, including last-admin checks.
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def user(request: Request, db=Depends(database, scope='function')):
        token = request.cookies.get(COOKIE, '')
        row = db.execute('SELECT u.id,u.username,u.name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1', (token_hash(token), time.time())).fetchone()
        if not row:
            fail(401, '请登录后继续')
        return dict(row)

    def access(project_id: int, actor=Depends(user), db=Depends(database, scope='function')):
        return member_access(db, project_id, actor)

    def permitted(permission):
        def check(actor=Depends(access)):
            if permission not in actor['permissions']:
                fail(403, '当前角色没有执行此操作的权限')
            return actor
        return check

    requirement_reader = permitted('requirement.read')
    requirement_writer = permitted('requirement.write')
    requirement_historian = permitted('requirement.history')
    task_reader = permitted('task.read')
    task_writer = permitted('task.write')
    milestone_reader = permitted('milestone.read')
    milestone_writer = permitted('milestone.write')
    statistics_reader = permitted('statistics.read')
    history_reader = permitted('history.read')
    uml_reader = permitted('uml.read')
    uml_writer = permitted('uml.write')
    ai_reader = permitted('ai.read')
    ai_writer = permitted('ai.write')
    ai_applier = permitted('ai.apply')

    def admin(actor=Depends(access)):
        if actor['role'] != 'admin':
            fail(403, '仅项目管理员可执行此操作')
        return actor

    def validated_scenario_payload(project_id, body, db):
        participants = list(body.participants)
        normalized = [value.casefold() for value in participants]
        if len(normalized) != len(set(normalized)):
            fail(422, '参与者名称不能重复')
        for index, participant in enumerate(participants, start=1):
            if any(ord(char) < 32 for char in participant):
                fail(422, f'第{index}个参与者包含不可生成的控制字符')
        participant_names = set(participants)
        messages = []
        for index, item in enumerate(body.messages, start=1):
            if item.from_participant not in participant_names:
                fail(422, f'第{index}条消息的发送方不在参与者清单中')
            if item.to_participant not in participant_names:
                fail(422, f'第{index}条消息的接收方不在参与者清单中')
            for value in (item.label, item.branch_condition):
                if any(ord(char) < 32 for char in value):
                    fail(422, f'第{index}条消息包含不可生成的控制字符')
            if not item.task_id:
                fail(422, f'第{index}条消息缺少来源任务ID')
            try:
                linked_task = task(db, project_id, item.task_id)
            except HTTPException:
                fail(422, f'第{index}条消息的来源任务不存在或不属于当前项目')
            messages.append({**item.model_dump(), 'task_id': linked_task['id']})
        return participants, messages

    def resume_after_ai_call(db, project_id, actor, permission):
        db.execute('BEGIN IMMEDIATE')
        current = member_access(db, project_id, actor)
        if permission not in current['permissions']:
            fail(403, 'AI 调用完成前权限已变化，结果未保存')
        return current

    @app.get('/api/health')
    def health(db=Depends(database, scope='function')):
        return {'ok': True, 'service': '爱管理 API', 'schema_version': db.execute('PRAGMA user_version').fetchone()[0]}

    @app.post('/api/auth/login')
    def login(body: LoginIn, response: Response, db=Depends(database, scope='function')):
        row = db.execute('SELECT * FROM users WHERE username=? AND active=1', (body.username,)).fetchone()
        valid = verify_password(body.password, row['password_hash'] if row else DUMMY_HASH)
        if not row or not valid:
            fail(401, '账号或密码错误')
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES(?,?,?)', (token_hash(token), row['id'], time.time() + SESSION_SECONDS))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite='strict', secure=os.environ.get('AIMANAGER_SECURE_COOKIE') == '1', path='/api')
        return {k: row[k] for k in ('id', 'username', 'name')}

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request, response: Response, db=Depends(database, scope='function')):
        db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(request.cookies.get(COOKIE, '')),))
        response.delete_cookie(COOKIE, path='/api')

    @app.get('/api/auth/me')
    def me(actor=Depends(user)):
        return actor

    @app.get('/api/projects')
    def projects(actor=Depends(user), db=Depends(database, scope='function')):
        rows = db.execute('SELECT p.* FROM projects p JOIN memberships m ON p.id=m.project_id WHERE m.user_id=? AND m.active=1 ORDER BY p.id', (actor['id'],))
        return [{**dict(row), **{k: v for k, v in public_access(member_access(db, row['id'], actor)).items() if k not in actor}} for row in rows]

    @app.get('/api/projects/{project_id}')
    def project(project_id: int, actor=Depends(access), db=Depends(database, scope='function')):
        return {**dict(db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()),
                **{k: v for k, v in public_access(actor).items() if k not in ('id', 'username', 'name')}}

    @app.get('/api/projects/{project_id}/members')
    def members(project_id: int, actor=Depends(access), db=Depends(database, scope='function')):
        rows = db.execute('''SELECT u.id,u.username,u.name,m.role,m.custom_role_id,cr.name custom_role_name
            FROM memberships m JOIN users u ON u.id=m.user_id
            LEFT JOIN custom_roles cr ON cr.id=m.custom_role_id AND cr.project_id=m.project_id
            WHERE m.project_id=? AND m.active=1 AND u.active=1 ORDER BY u.id''', (project_id,))
        result = []
        for row in rows:
            item = dict(row)
            item['role_key'] = f"custom:{item['custom_role_id']}" if item['custom_role_id'] else item['role']
            item['role_name'] = item['custom_role_name'] or {'admin': '管理员', 'member': '成员', 'observer': '观察者'}[item['role']]
            item.update(capacity(db, project_id, item['id']))
            result.append(item)
        return result

    @app.post('/api/projects/{project_id}/members', status_code=201)
    def add_member(project_id: int, body: MemberIn, actor=Depends(admin), db=Depends(database, scope='function')):
        target = db.execute('SELECT id FROM users WHERE username=? AND active=1', (body.username,)).fetchone()
        if not target:
            fail(404, '账号不存在或已停用')
        uid = target['id']
        old = db.execute('SELECT * FROM memberships WHERE project_id=? AND user_id=?', (project_id, uid)).fetchone()
        if old and old['active']:
            fail(409, '此账号已是项目成员')
        role, custom_role_id = parse_role(db, project_id, body.role)
        db.execute('''INSERT INTO memberships(project_id,user_id,role,active,custom_role_id) VALUES(?,?,?,1,?)
            ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role,active=1,custom_role_id=excluded.custom_role_id''',
            (project_id, uid, role, custom_role_id))
        result = {'user_id': uid, 'role': body.role, 'active': True}
        event(db, project_id, 'membership', str(uid), 'member_added', actor['id'], dict(old) if old else None, result)
        return result

    def change_member(project_id, uid, role_value, active, actor, db):
        old = db.execute('SELECT * FROM memberships WHERE project_id=? AND user_id=? AND active=1', (project_id, uid)).fetchone()
        if not old:
            fail(404, '成员不存在')
        role, custom_role_id = parse_role(db, project_id, role_value) if role_value else (old['role'], old['custom_role_id'])
        if old['role'] == 'admin' and old['custom_role_id'] is None and (not active or role != 'admin' or custom_role_id is not None):
            others = db.execute("SELECT COUNT(*) FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.project_id=? AND m.role='admin' AND m.active=1 AND u.active=1 AND m.user_id<>?", (project_id, uid)).fetchone()[0]
            if not others:
                fail(409, '必须保留至少一名有效管理员')
        db.execute('UPDATE memberships SET role=?,custom_role_id=?,active=? WHERE project_id=? AND user_id=?', (role, custom_role_id, active, project_id, uid))
        actual_role = f'custom:{custom_role_id}' if custom_role_id else role
        result = {'user_id': uid, 'role': actual_role, 'active': bool(active)}
        event(db, project_id, 'membership', str(uid), 'role_changed' if active else 'member_removed', actor['id'], dict(old), result)
        return result

    @app.patch('/api/projects/{project_id}/members/{user_id}')
    def edit_member(project_id: int, user_id: int, body: RoleIn, actor=Depends(admin), db=Depends(database, scope='function')):
        return change_member(project_id, user_id, body.role, 1, actor, db)

    @app.patch('/api/projects/{project_id}/members/{user_id}/capacity')
    def edit_member_capacity(project_id: int, user_id: int, body: CapacityIn,
                             actor=Depends(task_writer), db=Depends(database, scope='function')):
        member = db.execute('''SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id
            WHERE m.project_id=? AND m.user_id=? AND m.active=1 AND u.active=1''',
            (project_id, user_id)).fetchone()
        if not member:
            fail(404, '有效项目成员不存在')
        old = capacity(db, project_id, user_id)
        if body.version != old['capacity_version']:
            fail(409, '成员容量已被更新，请刷新后重试')
        stamp = now()
        values = (body.weekly_capacity_hours,
                  body.available_from.isoformat() if body.available_from else None,
                  body.available_to.isoformat() if body.available_to else None,
                  json.dumps(body.skill_tags, ensure_ascii=False), actor['id'], stamp)
        if old['capacity_version'] == 0:
            db.execute('''INSERT INTO member_capacities(project_id,user_id,weekly_capacity_hours,available_from,
                available_to,skill_tags_json,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)''',
                (project_id, user_id, *values))
        else:
            db.execute('''UPDATE member_capacities SET weekly_capacity_hours=?,available_from=?,available_to=?,
                skill_tags_json=?,version=version+1,updated_by=?,updated_at=? WHERE project_id=? AND user_id=?''',
                (*values, project_id, user_id))
        result = capacity(db, project_id, user_id)
        event(db, project_id, 'member_capacity', str(user_id), 'capacity_updated', actor['id'], old, result,
              body.reason.strip())
        return {'user_id': user_id, **result}

    @app.delete('/api/projects/{project_id}/members/{user_id}', status_code=204)
    def remove_member(project_id: int, user_id: int, actor=Depends(admin), db=Depends(database, scope='function')):
        change_member(project_id, user_id, None, 0, actor, db)

    @app.get('/api/projects/{project_id}/requirements')
    def requirements(project_id: int, q: str = '', actor=Depends(requirement_reader), db=Depends(database, scope='function')):
        rows = db.execute('SELECT pk FROM requirements WHERE project_id=? ORDER BY pk DESC', (project_id,))
        result = [requirement(db, project_id, f"REQ-{r['pk']:03d}") for r in rows]
        query = q.strip().casefold()
        return [r for r in result if query in ' '.join(str(r[k]) for k in
            ('id', 'title', 'description', 'source', 'story_role')).casefold()]

    @app.post('/api/projects/{project_id}/requirements', status_code=201)
    def create_requirement(project_id: int, body: RequirementIn, actor=Depends(requirement_writer), db=Depends(database, scope='function')):
        pk = db.execute('''INSERT INTO requirements(project_id,title,description,source,priority,acceptance_criteria,
            story_role,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',
            (project_id, body.title, body.description, body.source, body.priority,
             body.acceptance_criteria, body.story_role, actor['id'], now())).lastrowid
        result = requirement(db, project_id, f'REQ-{pk:03d}')
        event(db, project_id, 'requirement', result['id'], 'created', actor['id'], None, result)
        return result

    @app.get('/api/projects/{project_id}/requirements/{req_id}')
    def get_requirement(project_id: int, req_id: str, actor=Depends(requirement_reader), db=Depends(database, scope='function')):
        return requirement(db, project_id, req_id)

    @app.patch('/api/projects/{project_id}/requirements/{req_id}')
    def edit_requirement(project_id: int, req_id: str, body: RequirementEdit,
                         actor=Depends(requirement_writer), db=Depends(database, scope='function')):
        old = requirement(db, project_id, req_id)
        if body.version != old['version']:
            fail(409, '需求已被更新，请刷新后重试')
        linked_tasks = [task(db, project_id, f"T-{row['pk']:03d}") for row in db.execute(
            'SELECT pk FROM tasks WHERE project_id=? AND requirement_pk=? AND cancelled_at IS NULL ORDER BY pk',
            (project_id, key(req_id, 'REQ')))]
        changed_at = now()
        new_story_role = old['story_role'] if body.story_role is None else body.story_role
        db.execute('''INSERT INTO requirement_versions(project_id,requirement_pk,version,title,description,source,priority,
            acceptance_criteria,story_role,changed_by,changed_at,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (project_id, key(req_id, 'REQ'), old['version'], old['title'], old['description'], old['source'],
             old['priority'], old['acceptance_criteria'], old['story_role'], actor['id'], changed_at, body.reason))
        db.execute('''UPDATE requirements SET title=?,description=?,source=?,priority=?,acceptance_criteria=?,
            story_role=?,version=version+1 WHERE project_id=? AND pk=?''',
            (body.title, body.description, body.source, body.priority, body.acceptance_criteria,
             new_story_role, project_id, key(req_id, 'REQ')))
        db.execute('''UPDATE tasks SET review_required=1,version=version+1,updated_at=?
            WHERE project_id=? AND requirement_pk=? AND cancelled_at IS NULL''',
            (changed_at, project_id, key(req_id, 'REQ')))
        result = requirement(db, project_id, req_id)
        event(db, project_id, 'requirement', req_id, 'updated', actor['id'], old, result, body.reason)
        for old_task in linked_tasks:
            changed_task = task(db, project_id, old_task['id'])
            event(db, project_id, 'task', old_task['id'], 'source_requirement_changed', actor['id'],
                  old_task, changed_task, body.reason)
        return result

    @app.get('/api/projects/{project_id}/requirements/{req_id}/versions')
    def requirement_history(project_id: int, req_id: str, actor=Depends(requirement_historian), db=Depends(database, scope='function')):
        current = requirement(db, project_id, req_id)
        rows = [dict(row) for row in db.execute('''SELECT rv.*,u.name changed_by_name FROM requirement_versions rv
            JOIN users u ON u.id=rv.changed_by WHERE rv.project_id=? AND rv.requirement_pk=? ORDER BY rv.version DESC''',
            (project_id, key(req_id, 'REQ')))]
        latest = db.execute('''SELECT e.actor_id changed_by,u.name changed_by_name,e.occurred_at changed_at,e.reason
            FROM events e JOIN users u ON u.id=e.actor_id
            WHERE e.project_id=? AND e.entity_type='requirement' AND e.entity_id=? AND e.event_type='updated'
            ORDER BY e.id DESC LIMIT 1''', (project_id, req_id)).fetchone()
        current_change = dict(latest) if latest else {'changed_by': current['created_by'],
            'changed_by_name': current['creator_name'], 'changed_at': current['created_at'], 'reason': '初始版本'}
        rows.insert(0, {**{k: current[k] for k in ('version', 'title', 'description', 'source', 'priority',
                                                    'acceptance_criteria', 'story_role')},
                        **current_change})
        return rows

    @app.get('/api/projects/{project_id}/requirements/{req_id}/progress')
    def requirement_progress(project_id: int, req_id: str, actor=Depends(requirement_reader), db=Depends(database, scope='function')):
        if 'task.read' not in actor['permissions']:
            fail(403, '当前角色没有读取关联任务的权限')
        requirement(db, project_id, req_id)
        items = [task(db, project_id, f"T-{row['pk']:03d}") for row in db.execute(
            'SELECT pk FROM tasks WHERE project_id=? AND requirement_pk=? ORDER BY pk DESC',
            (project_id, key(req_id, 'REQ')))]
        active = [item for item in items if not item['cancelled']]
        return {'tasks': items, 'active_count': len(active),
                'completed_count': sum(item['status'] == '已完成' for item in active)}

    @app.get('/api/projects/{project_id}/requirements/{req_id}/planning-impact')
    def requirement_planning_impact(project_id: int, req_id: str, actor=Depends(requirement_reader),
                                    db=Depends(database, scope='function')):
        if 'task.read' not in actor['permissions']:
            fail(403, '查看排期影响需要任务读取权限')
        source = requirement(db, project_id, req_id)
        impact = planning_impact(db, project_id, key(req_id, 'REQ'),
            lambda pk: task(db, project_id, f'T-{pk:03d}'))
        runs = plan_runs(db, project_id, key(req_id, 'REQ'), 5)
        return {**impact, 'requirement_id': req_id, 'requirement_version': source['version'],
                'plan': plan_state(db, project_id), 'latest_run': runs[0] if runs else None}

    @app.get('/api/projects/{project_id}/requirements/{req_id}/planning-runs')
    def requirement_plan_runs(project_id: int, req_id: str, actor=Depends(requirement_reader),
                              db=Depends(database, scope='function')):
        if 'task.read' not in actor['permissions']:
            fail(403, '查看排期记录需要任务读取权限')
        requirement(db, project_id, req_id)
        return plan_runs(db, project_id, key(req_id, 'REQ'))

    @app.post('/api/projects/{project_id}/requirements/{req_id}/replan')
    def replan_requirement(project_id: int, req_id: str, body: ReplanIn, actor=Depends(admin),
                           db=Depends(database, scope='function')):
        source = requirement(db, project_id, req_id)
        if body.requirement_version != source['version']:
            fail(409, '需求已被更新，请刷新影响清单后重试')
        current_plan = plan_state(db, project_id)
        if body.plan_version != current_plan['version']:
            fail(409, '任务或容量数据已变化，请刷新影响清单后重试')
        calculation = calculate_replan(db, project_id, key(req_id, 'REQ'),
            lambda pk: task(db, project_id, f'T-{pk:03d}'),
            lambda user_id: capacity(db, project_id, user_id))
        stamp = now()
        proposal_records = [{k: v for k, v in proposal.items() if k not in ('pk', 'before')}
                            for proposal in calculation['proposals']]
        plan_version = touch_plan_state(db, project_id, actor['id'], stamp)
        if calculation['blocked']:
            db.execute('''INSERT INTO plan_runs(project_id,plan_version,requirement_pk,requirement_version,status,
                changes_json,conflicts_json,reason,triggered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (project_id, plan_version, key(req_id, 'REQ'), source['version'], 'blocked',
                 json.dumps(proposal_records, ensure_ascii=False),
                 json.dumps(calculation['conflicts'], ensure_ascii=False), body.reason, actor['id'], stamp))
            return {'applied': False, 'plan_version': plan_version, 'changes': proposal_records,
                    'conflicts': calculation['conflicts'], 'message': '存在无法自动排期的冲突，未修改任何任务'}

        changed_events = []
        for proposal in calculation['proposals']:
            review_value = 0 if proposal['pk'] in calculation['direct'] else int(proposal['before']['review_required'])
            db.execute('''UPDATE tasks SET planned_start=?,planned_end=?,review_required=?,version=version+1,updated_at=?
                WHERE project_id=? AND pk=?''',
                (proposal['after_start'], proposal['after_end'], review_value, stamp, project_id, proposal['pk']))
            after = task(db, project_id, proposal['task_id'])
            changed_events.append((proposal['before'], after, 'plan_recalculated'))
        proposed_pks = {proposal['pk'] for proposal in calculation['proposals']}
        for pk in calculation['direct'] - proposed_pks:
            before = task(db, project_id, f'T-{pk:03d}')
            if before['cancelled'] or not before['review_required']:
                continue
            db.execute('''UPDATE tasks SET review_required=0,version=version+1,updated_at=?
                WHERE project_id=? AND pk=?''', (stamp, project_id, pk))
            changed_events.append((before, task(db, project_id, before['id']), 'plan_review_confirmed'))
        applied_changes = []
        for before, after, action in changed_events:
            applied_changes.append({'task_id': after['id'], 'action': action,
                'before_start': before['planned_start'], 'before_end': before['planned_end'],
                'after_start': after['planned_start'], 'after_end': after['planned_end'],
                'task_version': after['version']})
        db.execute('''INSERT INTO plan_runs(project_id,plan_version,requirement_pk,requirement_version,status,
            changes_json,conflicts_json,reason,triggered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (project_id, plan_version, key(req_id, 'REQ'), source['version'], 'applied',
             json.dumps(applied_changes, ensure_ascii=False),
             json.dumps(calculation['conflicts'], ensure_ascii=False), body.reason, actor['id'], stamp))
        for before, after, action in changed_events:
            event(db, project_id, 'task', after['id'], action, actor['id'], before, after,
                  body.reason, touch_plan=False)
        return {'applied': True, 'plan_version': plan_version, 'changes': applied_changes,
                'conflicts': calculation['conflicts'], 'message': '排期已按依赖和成员容量更新'}

    @app.get('/api/projects/{project_id}/ai')
    def ai_center(project_id: int, actor=Depends(ai_reader), db=Depends(database, scope='function')):
        runs = list_ai_runs(db, project_id)
        thresholds = latest_risk_thresholds(db, project_id)
        return {'service': public_ai_settings(), 'plan_version': plan_state(db, project_id)['version'],
                'runs': runs, 'draft_count': sum(item['status'] == 'draft' for item in runs),
                'failed_count': sum(item['status'] == 'failed' for item in runs),
                'risk_thresholds': thresholds,
                'risk_threshold_history': list_risk_thresholds(db, project_id),
                'members': ai_members(db, project_id),
                'quality_targets': [{'id': f"REQ-{row['pk']:03d}", 'title': row['title']}
                                    for row in db.execute('''SELECT pk,title FROM requirements
                                        WHERE project_id=? ORDER BY pk''', (project_id,))],
                'actions': improvement_actions(db, project_id)}

    @app.get('/api/projects/{project_id}/ai/runs/{run_id}')
    def get_ai_run(project_id: int, run_id: int, actor=Depends(ai_reader),
                   db=Depends(database, scope='function')):
        result = load_ai_run(db, project_id, run_id)
        if not result:
            fail(404, 'AI 记录不存在')
        return result

    @app.post('/api/projects/{project_id}/ai/prd-breakdowns', status_code=201)
    def generate_prd_breakdown(project_id: int, body: AIPRDBreakdownIn, response: Response,
                               actor=Depends(ai_writer), db=Depends(database, scope='function')):
        if not {'requirement.read', 'task.read'}.issubset(actor['permissions']):
            fail(403, 'AI 需求拆解需要读取需求和任务的权限')
        input_version = plan_state(db, project_id)['version']
        input_data = {'source_name': body.source_name, 'prd_text': body.prd_text}
        settings = ai_settings()
        model_id, provider_url = settings['model_id'], public_provider_url(settings['endpoint'])
        db.commit()
        failure = None
        output = None
        try:
            raw, model_id, provider_url = call_structured('prd_breakdown', breakdown_prompt(), input_data)
            output = normalize_breakdown(raw, body.prd_text)
        except AIServiceError as caught:
            failure = caught
        current = resume_after_ai_call(db, project_id, actor, 'ai.write')
        result = save_ai_run(db, project_id, 'prd_breakdown', input_version, input_data,
                             model_id or '', provider_url, current['id'], now(), output=output, failure=failure)
        event(db, project_id, 'ai_run', str(result['id']), 'generation_failed' if failure else 'draft_created',
              current['id'], None, {'run_id': result['id'], 'capability': 'prd_breakdown',
                                    'status': result['status'], 'input_version': input_version}, touch_plan=False)
        if failure:
            response.status_code = failure.status_code
        return result

    @app.post('/api/projects/{project_id}/ai/forecasts', status_code=201)
    def generate_forecast(project_id: int, body: AIForecastIn, response: Response,
                          actor=Depends(ai_writer), db=Depends(database, scope='function')):
        if not {'task.read', 'history.read'}.issubset(actor['permissions']):
            fail(403, '进度预测需要读取任务和历史的权限')
        input_version = plan_state(db, project_id)['version']
        evidence = forecast_calculation(db, project_id,
            lambda pk: task(db, project_id, f'T-{pk:03d}'),
            lambda user_id: capacity(db, project_id, user_id), body.as_of_date)
        input_data = {'evidence': evidence}
        settings = ai_settings()
        model_id, provider_url = settings['model_id'], public_provider_url(settings['endpoint'])
        db.commit()
        failure = None
        output = None
        try:
            raw, model_id, provider_url = call_structured('progress_forecast', forecast_prompt(), input_data)
            output = {'evidence': evidence, 'explanation': validate_forecast_explanation(raw)}
        except AIServiceError as caught:
            failure = caught
        current = resume_after_ai_call(db, project_id, actor, 'ai.write')
        result = save_ai_run(db, project_id, 'progress_forecast', input_version, input_data,
                             model_id or '', provider_url, current['id'], now(), output=output, failure=failure)
        event(db, project_id, 'ai_run', str(result['id']), 'generation_failed' if failure else 'draft_created',
              current['id'], None, {'run_id': result['id'], 'capability': 'progress_forecast',
                                    'status': result['status'], 'input_version': input_version}, touch_plan=False)
        if failure:
            response.status_code = failure.status_code
        return result

    @app.post('/api/projects/{project_id}/ai/schedules', status_code=201)
    def generate_ai_schedule(project_id: int, body: AIScheduleIn, response: Response,
                             actor=Depends(ai_writer), db=Depends(database, scope='function')):
        if 'task.read' not in actor['permissions']:
            fail(403, '智能排期需要读取任务的权限')
        input_version = plan_state(db, project_id)['version']
        calculation = schedule_calculation(db, project_id,
            lambda pk: task(db, project_id, f'T-{pk:03d}'),
            lambda user_id: capacity(db, project_id, user_id), body.start_date)
        input_data = {'plan': calculation}
        settings = ai_settings()
        model_id, provider_url = settings['model_id'], public_provider_url(settings['endpoint'])
        db.commit()
        failure = None
        output = None
        try:
            raw, model_id, provider_url = call_structured('smart_schedule', schedule_prompt(), input_data)
            proposal_ids = [item['task_id'] for item in calculation['proposals']]
            output = {'plan': calculation,
                      'explanation': validate_schedule_explanation(raw, proposal_ids)}
        except AIServiceError as caught:
            failure = caught
        current = resume_after_ai_call(db, project_id, actor, 'ai.write')
        result = save_ai_run(db, project_id, 'smart_schedule', input_version, input_data,
                             model_id or '', provider_url, current['id'], now(), output=output, failure=failure)
        event(db, project_id, 'ai_run', str(result['id']), 'generation_failed' if failure else 'draft_created',
              current['id'], None, {'run_id': result['id'], 'capability': 'smart_schedule',
                                    'status': result['status'], 'input_version': input_version}, touch_plan=False)
        if failure:
            response.status_code = failure.status_code
        return result

    @app.post('/api/projects/{project_id}/ai/risks', status_code=201)
    def generate_risk_analysis(project_id: int, body: AIRiskIn, response: Response,
                               actor=Depends(ai_writer), db=Depends(database, scope='function')):
        if not {'task.read', 'history.read', 'statistics.read'}.issubset(actor['permissions']):
            fail(403, '风险预警需要读取任务、历史和统计的权限')
        current_thresholds = latest_risk_thresholds(db, project_id)
        changed = (float(body.overload_percent) != float(current_thresholds['overload_percent'])
                   or float(body.blocked_workdays) != float(current_thresholds['blocked_workdays']))
        if current_thresholds['version'] == 0 or changed:
            if changed and current_thresholds['version'] > 0 and not body.threshold_reason:
                fail(422, '修改风险阈值必须填写原因')
            threshold_version = current_thresholds['version'] + 1
            threshold_reason = body.threshold_reason or '首次确认风险阈值'
            db.execute('''INSERT INTO risk_threshold_versions(project_id,version,overload_percent,
                blocked_workdays,changed_by,changed_at,reason) VALUES(?,?,?,?,?,?,?)''',
                (project_id, threshold_version, body.overload_percent, body.blocked_workdays,
                 actor['id'], now(), threshold_reason))
            event(db, project_id, 'risk_threshold', str(threshold_version),
                  'created' if current_thresholds['version'] == 0 else 'changed', actor['id'],
                  current_thresholds if current_thresholds['version'] else None,
                  {'version': threshold_version, 'overload_percent': body.overload_percent,
                   'blocked_workdays': body.blocked_workdays}, threshold_reason, touch_plan=False)
            current_thresholds = latest_risk_thresholds(db, project_id)
        input_version = plan_state(db, project_id)['version']
        evidence = risk_calculation(db, project_id,
            lambda pk: task(db, project_id, f'T-{pk:03d}'),
            lambda user_id: capacity(db, project_id, user_id),
            {key_name: current_thresholds[key_name] for key_name in
             ('version', 'overload_percent', 'blocked_workdays')}, body.as_of_date)
        members = ai_members(db, project_id)
        input_data = {'evidence': evidence, 'members': members}
        settings = ai_settings()
        model_id, provider_url = settings['model_id'], public_provider_url(settings['endpoint'])
        db.commit()
        failure = None
        output = None
        try:
            raw, model_id, provider_url = call_structured('risk_analysis', risk_prompt(), input_data)
            output = {'evidence': evidence, 'member_ids': [item['id'] for item in members],
                      'analysis': validate_risk_analysis(raw, evidence, {item['id'] for item in members})}
        except AIServiceError as caught:
            failure = caught
        current = resume_after_ai_call(db, project_id, actor, 'ai.write')
        result = save_ai_run(db, project_id, 'risk_analysis', input_version, input_data,
                             model_id or '', provider_url, current['id'], now(), output=output, failure=failure)
        event(db, project_id, 'ai_run', str(result['id']), 'generation_failed' if failure else 'draft_created',
              current['id'], None, {'run_id': result['id'], 'capability': 'risk_analysis',
                                    'status': result['status'], 'input_version': input_version}, touch_plan=False)
        if failure:
            response.status_code = failure.status_code
        return result

    @app.post('/api/projects/{project_id}/ai/quality-analyses', status_code=201)
    def generate_quality_analysis(project_id: int, body: AIQualityIn, response: Response,
                                  actor=Depends(ai_writer), db=Depends(database, scope='function')):
        if not {'requirement.read', 'task.read'}.issubset(actor['permissions']):
            fail(403, '质量分析需要读取需求和任务的权限')
        target = requirement(db, project_id, body.target_requirement_id)
        check_owner(db, project_id, body.owner_id)
        artifacts = [item.model_dump(mode='json') for item in body.artifacts]
        input_version = plan_state(db, project_id)['version']
        input_data = {'target_requirement_id': target['id'], 'target_requirement_title': target['title'],
                      'owner_id': body.owner_id, 'due_date': body.due_date.isoformat() if body.due_date else None,
                      'artifacts': artifacts}
        settings = ai_settings()
        model_id, provider_url = settings['model_id'], public_provider_url(settings['endpoint'])
        db.commit()
        failure = None
        output = None
        try:
            raw, model_id, provider_url = call_structured('quality_analysis', quality_prompt(), input_data)
            output = {'artifacts': artifacts, 'analysis': validate_quality_analysis(raw, artifacts)}
        except AIServiceError as caught:
            failure = caught
        current = resume_after_ai_call(db, project_id, actor, 'ai.write')
        result = save_ai_run(db, project_id, 'quality_analysis', input_version, input_data,
                             model_id or '', provider_url, current['id'], now(), output=output, failure=failure)
        event(db, project_id, 'ai_run', str(result['id']), 'generation_failed' if failure else 'draft_created',
              current['id'], None, {'run_id': result['id'], 'capability': 'quality_analysis',
                                    'status': result['status'], 'input_version': input_version}, touch_plan=False)
        if failure:
            response.status_code = failure.status_code
        return result

    @app.post('/api/projects/{project_id}/ai/efficiency-analyses', status_code=201)
    def generate_efficiency_analysis(project_id: int, body: AIEfficiencyIn, response: Response,
                                     actor=Depends(ai_writer), db=Depends(database, scope='function')):
        if not {'task.read', 'history.read', 'statistics.read'}.issubset(actor['permissions']):
            fail(403, '效率分析需要读取任务、历史和统计的权限')
        input_version = plan_state(db, project_id)['version']
        evidence = efficiency_calculation(db, project_id,
            lambda pk: task(db, project_id, f'T-{pk:03d}'),
            lambda user_id: capacity(db, project_id, user_id), body.as_of_date)
        members = ai_members(db, project_id)
        input_data = {'evidence': evidence, 'members': members}
        settings = ai_settings()
        model_id, provider_url = settings['model_id'], public_provider_url(settings['endpoint'])
        db.commit()
        failure = None
        output = None
        try:
            raw, model_id, provider_url = call_structured('efficiency_analysis', efficiency_prompt(), input_data)
            output = {'evidence': evidence, 'member_ids': [item['id'] for item in members],
                      'analysis': validate_efficiency_analysis(raw, evidence, {item['id'] for item in members})}
        except AIServiceError as caught:
            failure = caught
        current = resume_after_ai_call(db, project_id, actor, 'ai.write')
        result = save_ai_run(db, project_id, 'efficiency_analysis', input_version, input_data,
                             model_id or '', provider_url, current['id'], now(), output=output, failure=failure)
        event(db, project_id, 'ai_run', str(result['id']), 'generation_failed' if failure else 'draft_created',
              current['id'], None, {'run_id': result['id'], 'capability': 'efficiency_analysis',
                                    'status': result['status'], 'input_version': input_version}, touch_plan=False)
        if failure:
            response.status_code = failure.status_code
        return result

    @app.patch('/api/projects/{project_id}/ai/runs/{run_id}')
    def edit_ai_run(project_id: int, run_id: int, body: AIOutputEditIn,
                    actor=Depends(ai_writer), db=Depends(database, scope='function')):
        old = load_ai_run(db, project_id, run_id)
        if not old:
            fail(404, 'AI 记录不存在')
        if old['status'] != 'draft':
            fail(409, '只有待审查草案可以修改')
        if body.version != old['version']:
            fail(409, 'AI 草案已被更新，请刷新后重试')
        try:
            output = validate_review_output(old['capability'], body.output, old['original_output'])
        except AIServiceError as caught:
            fail(caught.status_code, caught.message)
        stamp = now()
        db.execute('''UPDATE ai_runs SET edited_output_json=?,version=version+1,decision_reason=?
            WHERE project_id=? AND id=?''',
            (json.dumps(output, ensure_ascii=False), body.reason, project_id, run_id))
        db.execute('''INSERT INTO ai_reviews(project_id,run_id,action,output_json,reason,actor_id,created_at)
            VALUES(?,?,?,?,?,?,?)''',
            (project_id, run_id, 'edited', json.dumps(output, ensure_ascii=False), body.reason,
             actor['id'], stamp))
        event(db, project_id, 'ai_run', str(run_id), 'draft_edited', actor['id'],
              {'version': old['version']}, {'version': old['version'] + 1}, body.reason, touch_plan=False)
        return load_ai_run(db, project_id, run_id)

    @app.post('/api/projects/{project_id}/ai/runs/{run_id}/reject')
    def reject_ai_run(project_id: int, run_id: int, body: AIReviewIn,
                      actor=Depends(ai_writer), db=Depends(database, scope='function')):
        old = load_ai_run(db, project_id, run_id)
        if not old:
            fail(404, 'AI 记录不存在')
        if old['status'] != 'draft':
            fail(409, '只有待审查草案可以否决')
        if body.version != old['version']:
            fail(409, 'AI 草案已被更新，请刷新后重试')
        stamp = now()
        db.execute('''UPDATE ai_runs SET status='rejected',version=version+1,decided_by=?,decided_at=?,
            decision_reason=? WHERE project_id=? AND id=?''',
            (actor['id'], stamp, body.reason, project_id, run_id))
        db.execute('''INSERT INTO ai_reviews(project_id,run_id,action,output_json,reason,actor_id,created_at)
            VALUES(?,?,?,?,?,?,?)''',
            (project_id, run_id, 'rejected', json.dumps(old['output'], ensure_ascii=False),
             body.reason, actor['id'], stamp))
        event(db, project_id, 'ai_run', str(run_id), 'rejected', actor['id'],
              {'status': 'draft'}, {'status': 'rejected'}, body.reason, touch_plan=False)
        return load_ai_run(db, project_id, run_id)

    @app.post('/api/projects/{project_id}/ai/runs/{run_id}/apply')
    def apply_ai_run(project_id: int, run_id: int, body: AIReviewIn,
                     actor=Depends(ai_applier), db=Depends(database, scope='function')):
        if not body.operation_id:
            fail(422, '确认应用必须提供操作标识')
        existing = db.execute('SELECT id FROM ai_runs WHERE project_id=? AND applied_operation_id=?',
                              (project_id, body.operation_id)).fetchone()
        if existing:
            if existing['id'] == run_id:
                return load_ai_run(db, project_id, run_id)
            fail(409, '操作标识已用于其他 AI 草案')
        old = load_ai_run(db, project_id, run_id)
        if not old:
            fail(404, 'AI 记录不存在')
        if old['status'] == 'applied':
            fail(409, '此 AI 草案已经应用')
        if old['status'] != 'draft':
            fail(409, '只有待审查草案可以应用')
        if body.version != old['version']:
            fail(409, 'AI 草案已被更新，请刷新后重试')
        if old['input_version'] != plan_state(db, project_id)['version']:
            fail(409, '需求、任务、容量或排期已变化，请重新生成 AI 草案')
        try:
            output = validate_review_output(old['capability'], old['output'], old['original_output'])
        except AIServiceError as caught:
            fail(caught.status_code, caught.message)

        stamp = now()
        if old['capability'] == 'prd_breakdown':
            if not {'requirement.write', 'task.write'}.issubset(actor['permissions']):
                fail(403, '应用需求拆解需要需求和任务写权限')
            if not output['stories']:
                fail(422, '没有具备可定位来源的故事可应用')
            local_tasks = {}
            pending_dependencies = []
            source_name = old['input']['source_name']
            for story in output['stories']:
                requirement_pk = db.execute('''INSERT INTO requirements(project_id,title,description,source,priority,
                    acceptance_criteria,story_role,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                    (project_id, story['story'], f"作为{story['role']}，{story['story']}",
                     ('AI拆解 · ' + source_name)[:200], story['priority'],
                     '\n'.join(story['acceptance_criteria']), story['role'], actor['id'], stamp)).lastrowid
                created_requirement = requirement(db, project_id, f'REQ-{requirement_pk:03d}')
                event(db, project_id, 'requirement', created_requirement['id'], 'ai_created', actor['id'], None,
                      created_requirement, body.reason)
                for draft_task in story['tasks']:
                    task_pk = db.execute('''INSERT INTO tasks(project_id,requirement_pk,title,description,owner_id,
                        sprint,estimated_hours,remaining_hours,required_skills_json,created_by,created_at,updated_at)
                        VALUES(?,?,?,?,NULL,'S5',?,?,?,?,?,?)''',
                        (project_id, requirement_pk, draft_task['title'], draft_task['description'],
                         draft_task['estimate_hours'], draft_task['estimate_hours'],
                         json.dumps(draft_task['required_skills'], ensure_ascii=False), actor['id'], stamp, stamp)).lastrowid
                    local_tasks[draft_task['local_id']] = task_pk
                    pending_dependencies.extend((draft_task['local_id'], dependency)
                                                for dependency in draft_task['depends_on'])
                    created_task = task(db, project_id, f'T-{task_pk:03d}')
                    event(db, project_id, 'task', created_task['id'], 'ai_created', actor['id'], None,
                          created_task, body.reason)
            for local_task, local_dependency in pending_dependencies:
                task_pk, dependency_pk = local_tasks[local_task], local_tasks[local_dependency]
                db.execute('''INSERT INTO task_dependencies(project_id,task_pk,depends_on_pk,reason,created_by,created_at)
                    VALUES(?,?,?,?,?,?)''',
                    (project_id, task_pk, dependency_pk, 'AI 拆解建议经人工确认', actor['id'], stamp))
                event(db, project_id, 'task_dependency', f'T-{task_pk:03d}:T-{dependency_pk:03d}',
                      'dependency_added', actor['id'], None,
                      {'task_id': f'T-{task_pk:03d}', 'depends_on_id': f'T-{dependency_pk:03d}'},
                      body.reason)
        elif old['capability'] == 'progress_forecast':
            if 'task.read' not in actor['permissions']:
                fail(403, '确认进度预测需要任务读取权限')
        elif old['capability'] == 'smart_schedule':
            if 'task.write' not in actor['permissions']:
                fail(403, '应用智能排期需要任务写权限')
            plan = output['plan']
            if plan['blocked']:
                fail(409, '排期仍有阻断冲突，不能应用')
            changes = []
            for proposal in plan['proposals']:
                before = task(db, project_id, proposal['task_id'])
                if before['cancelled'] or before['status'] != '待办' or before['plan_locked']:
                    fail(409, f"{before['id']} 已不可由智能排期移动")
                check_owner(db, project_id, proposal['after_owner_id'])
                owner_capacity = capacity(db, project_id, proposal['after_owner_id'])
                member_skills = {value.casefold() for value in owner_capacity['skill_tags']}
                if not {value.casefold() for value in before['required_skills']}.issubset(member_skills):
                    fail(422, f"{before['id']} 的建议负责人不满足技能要求")
                db.execute('''UPDATE tasks SET owner_id=?,planned_start=?,planned_end=?,version=version+1,updated_at=?
                    WHERE project_id=? AND pk=?''',
                    (proposal['after_owner_id'], proposal['after_start'], proposal['after_end'], stamp,
                     project_id, key(before['id'], 'T')))
                after = task(db, project_id, before['id'])
                changes.append((before, after))
            if changes:
                touch_plan_state(db, project_id, actor['id'], stamp)
            for before, after in changes:
                event(db, project_id, 'task', after['id'], 'ai_schedule_applied', actor['id'],
                      before, after, body.reason, touch_plan=False)
        elif old['capability'] == 'quality_analysis':
            if 'task.write' not in actor['permissions']:
                fail(403, '应用质量分析需要任务写权限')
            target = requirement(db, project_id, old['input']['target_requirement_id'])
            owner_id = old['input'].get('owner_id')
            check_owner(db, project_id, owner_id)
            for issue in output['analysis']['issues']:
                description = ('AI质量分析经人工核实后转为任务\n'
                    f"问题类型：{'缺陷' if issue['task_kind'] == 'defect' else '改进'}\n"
                    f"来源：{issue['file_name']} · {issue['location']}\n"
                    f"依据：{issue['evidence']}\n影响：{issue['impact']}\n建议：{issue['recommendation']}")[:10000]
                task_pk = db.execute('''INSERT INTO tasks(project_id,requirement_pk,title,description,owner_id,
                    due_date,sprint,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,'S6',?,?,?)''',
                    (project_id, key(target['id'], 'REQ'), issue['title'], description, owner_id,
                     old['input'].get('due_date'), actor['id'], stamp, stamp)).lastrowid
                created = task(db, project_id, f'T-{task_pk:03d}')
                event(db, project_id, 'task', created['id'], 'quality_issue_created', actor['id'], None,
                      created, body.reason)
        elif old['capability'] in {'risk_analysis', 'efficiency_analysis'}:
            advice_items = (output['analysis']['risks'] if old['capability'] == 'risk_analysis'
                            else output['analysis']['bottlenecks'])
            evidence_items = ({item['risk_id']: item for item in output['evidence']['risks']}
                              if old['capability'] == 'risk_analysis'
                              else {item['key']: item for item in output['evidence']['metrics']})
            for advice in advice_items:
                item_key = advice.get('risk_id') or advice['metric_key']
                source = evidence_items[item_key]
                owner_id = advice['owner_id']
                check_owner(db, project_id, owner_id)
                if old['capability'] == 'risk_analysis':
                    title = source['title']
                    description = f"{source['evidence']}\n应对建议：{advice['recommendation']}"
                    due_date = advice['next_check_date']
                    next_check_date = advice['next_check_date']
                    metric_key = source['metric_key']
                    metric_value = source['metric_value']
                    review_metric = f"复核 {metric_key} 是否低于 {metric_value} {source['unit']}"
                    source_kind = 'risk'
                else:
                    title = advice['action_title']
                    description = f"瓶颈：{advice['bottleneck']}\n改进建议：{advice['recommendation']}"
                    due_date = advice['due_date']
                    next_check_date = advice['due_date']
                    metric_key = advice['metric_key']
                    metric_value = advice['metric_value']
                    review_metric = advice['review_metric']
                    source_kind = 'efficiency'
                db.execute('''INSERT INTO improvement_actions(project_id,source_run_id,source_item_key,
                    source_kind,title,description,owner_id,due_date,next_check_date,baseline_metric_key,
                    baseline_metric_value,review_metric,created_by,created_at,updated_by,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (project_id, run_id, item_key, source_kind, title, description, owner_id,
                     due_date, next_check_date, metric_key, metric_value, review_metric,
                     actor['id'], stamp, actor['id'], stamp))
        else:
            fail(422, 'AI 能力类型无效')

        db.execute('''UPDATE ai_runs SET status='applied',version=version+1,decided_by=?,decided_at=?,
            decision_reason=?,applied_operation_id=? WHERE project_id=? AND id=?''',
            (actor['id'], stamp, body.reason, body.operation_id, project_id, run_id))
        db.execute('''INSERT INTO ai_reviews(project_id,run_id,action,output_json,reason,operation_id,actor_id,created_at)
            VALUES(?,?,?,?,?,?,?,?)''',
            (project_id, run_id, 'applied', json.dumps(output, ensure_ascii=False), body.reason,
             body.operation_id, actor['id'], stamp))
        event(db, project_id, 'ai_run', str(run_id), 'applied', actor['id'],
              {'status': 'draft'}, {'status': 'applied', 'operation_id': body.operation_id},
              body.reason, touch_plan=False)
        return load_ai_run(db, project_id, run_id)

    @app.patch('/api/projects/{project_id}/ai/actions/{action_id}')
    def update_improvement_action(project_id: int, action_id: int, body: ImprovementActionEditIn,
                                  actor=Depends(ai_applier), db=Depends(database, scope='function')):
        old = improvement_action(db, project_id, action_id)
        if body.version != old['version']:
            fail(409, '改进行动已被更新，请刷新后重试')
        if old['status'] == '已完成':
            fail(409, '已完成行动保留为历史记录，不能重新打开')
        if body.status == '已完成':
            if body.current_metric_value is None or not body.review_note:
                fail(422, '关闭行动必须填写复核指标和复核说明')
            if body.current_metric_value >= old['baseline_metric_value']:
                fail(409, '当前指标尚未优于行动创建时的基线，不能关闭')
        stamp = now()
        db.execute('''UPDATE improvement_actions SET status=?,current_metric_value=?,review_note=?,
            version=version+1,updated_by=?,updated_at=?,completed_at=? WHERE project_id=? AND id=?''',
            (body.status, body.current_metric_value, body.review_note, actor['id'], stamp,
             stamp if body.status == '已完成' else None, project_id, action_id))
        result = improvement_action(db, project_id, action_id)
        event(db, project_id, 'improvement_action', str(action_id),
              'completed' if body.status == '已完成' else 'status_changed', actor['id'], old,
              result, body.review_note, touch_plan=False)
        return result

    @app.get('/api/projects/{project_id}/uml')
    def uml_center(project_id: int, actor=Depends(uml_reader), db=Depends(database, scope='function')):
        source_version = plan_state(db, project_id)['version']
        use_case = latest_generation(db, project_id, 'use_case', 'project')
        return {'source_version': source_version, 'use_case': use_case,
                'use_case_stale': bool(use_case and use_case['source_version'] != source_version),
                'scenarios': scenarios(db, project_id)}

    @app.post('/api/projects/{project_id}/uml/use-case/generate')
    def generate_use_case(project_id: int, body: UseCaseGenerateIn, actor=Depends(uml_writer),
                          db=Depends(database, scope='function')):
        if not {'requirement.read', 'task.read'}.issubset(actor['permissions']):
            fail(403, '生成用例图需要读取需求和任务的权限')
        source_version = plan_state(db, project_id)['version']
        if body.source_version != source_version:
            fail(409, '需求或任务已变化，请刷新UML来源后重试')
        before = latest_generation(db, project_id, 'use_case', 'project')
        content, warnings = build_use_case(
            db, project_id,
            lambda pk: requirement(db, project_id, f'REQ-{pk:03d}'),
            lambda pk: task(db, project_id, f'T-{pk:03d}'))
        project_name = db.execute('SELECT name FROM projects WHERE id=?', (project_id,)).fetchone()['name']
        content['project_name'] = project_name
        result = save_generation(db, project_id, 'use_case', 'project', source_version,
                                 content, warnings, actor['id'], now())
        event(db, project_id, 'uml_generation', f'use_case:{result["version"]}', 'generated',
              actor['id'], before, result, touch_plan=False)
        return result

    @app.get('/api/projects/{project_id}/uml/scenarios')
    def list_uml_scenarios(project_id: int, actor=Depends(uml_reader),
                           db=Depends(database, scope='function')):
        return scenarios(db, project_id)

    @app.post('/api/projects/{project_id}/uml/scenarios', status_code=201)
    def create_uml_scenario(project_id: int, body: SequenceScenarioIn, actor=Depends(uml_writer),
                            db=Depends(database, scope='function')):
        if 'task.read' not in actor['permissions']:
            fail(403, '维护时序场景需要读取关联任务的权限')
        participants, messages = validated_scenario_payload(project_id, body, db)
        stamp = now()
        try:
            scenario_id = db.execute('''INSERT INTO uml_scenarios(project_id,name,description,participants_json,
                messages_json,created_by,created_at,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                (project_id, body.name, body.description,
                 json.dumps(participants, ensure_ascii=False), json.dumps(messages, ensure_ascii=False),
                 actor['id'], stamp, actor['id'], stamp)).lastrowid
        except sqlite3.IntegrityError:
            fail(409, '场景名称已存在')
        result = scenario(db, project_id, scenario_id)
        event(db, project_id, 'uml_scenario', str(scenario_id), 'created', actor['id'], None, result,
              touch_plan=False)
        return result

    @app.get('/api/projects/{project_id}/uml/scenarios/{scenario_id}')
    def get_uml_scenario(project_id: int, scenario_id: int, actor=Depends(uml_reader),
                         db=Depends(database, scope='function')):
        result = scenario(db, project_id, scenario_id)
        if not result:
            fail(404, 'UML场景不存在')
        return result

    @app.patch('/api/projects/{project_id}/uml/scenarios/{scenario_id}')
    def edit_uml_scenario(project_id: int, scenario_id: int, body: SequenceScenarioEdit,
                          actor=Depends(uml_writer), db=Depends(database, scope='function')):
        if 'task.read' not in actor['permissions']:
            fail(403, '维护时序场景需要读取关联任务的权限')
        old = scenario(db, project_id, scenario_id)
        if not old:
            fail(404, 'UML场景不存在')
        if body.version != old['version']:
            fail(409, 'UML场景已被更新，请刷新后重试')
        participants, messages = validated_scenario_payload(project_id, body, db)
        stamp = now()
        try:
            db.execute('''UPDATE uml_scenarios SET name=?,description=?,participants_json=?,messages_json=?,
                version=version+1,updated_by=?,updated_at=? WHERE project_id=? AND id=?''',
                (body.name, body.description, json.dumps(participants, ensure_ascii=False),
                 json.dumps(messages, ensure_ascii=False), actor['id'], stamp, project_id, scenario_id))
        except sqlite3.IntegrityError:
            fail(409, '场景名称已存在')
        result = scenario(db, project_id, scenario_id)
        event(db, project_id, 'uml_scenario', str(scenario_id), 'updated', actor['id'], old, result,
              touch_plan=False)
        return result

    @app.post('/api/projects/{project_id}/uml/scenarios/{scenario_id}/generate')
    def generate_sequence(project_id: int, scenario_id: int, body: SequenceGenerateIn,
                          actor=Depends(uml_writer), db=Depends(database, scope='function')):
        if 'task.read' not in actor['permissions']:
            fail(403, '生成时序图需要读取关联任务的权限')
        source = scenario(db, project_id, scenario_id)
        if not source:
            fail(404, 'UML场景不存在')
        if body.scenario_version != source['version']:
            fail(409, 'UML场景已被更新，请刷新后重试')
        # Revalidate persisted structured data before appending a generation version.
        participants = source['participants']
        participant_names = set(participants)
        for index, message in enumerate(source['messages'], start=1):
            if message['from_participant'] not in participant_names or message['to_participant'] not in participant_names:
                fail(422, f'第{index}条消息引用了无效参与者')
            if not message.get('task_id'):
                fail(422, f'第{index}条消息缺少来源任务ID')
        content = build_sequence(source, lambda task_id: task(db, project_id, task_id))
        before = source['latest_generation']
        result = save_generation(db, project_id, 'sequence', f'scenario:{scenario_id}', source['version'],
                                 content, [], actor['id'], now())
        event(db, project_id, 'uml_generation', f'sequence:{scenario_id}:{result["version"]}',
              'generated', actor['id'], before, result, touch_plan=False)
        return result

    @app.get('/api/projects/{project_id}/tasks')
    def tasks(project_id: int, q: str = '', status: str = '', owner_id: str = '',
              cancelled: str = 'active',
              actor=Depends(task_reader), db=Depends(database, scope='function')):
        if status and status not in ('待办', '进行中', '待验收', '已完成'):
            fail(422, '任务状态筛选值无效')
        if cancelled not in ('active', 'only', 'all'):
            fail(422, '取消状态筛选值无效')
        if owner_id and owner_id != 'unassigned':
            try:
                parsed_owner = int(owner_id)
                if parsed_owner <= 0:
                    raise ValueError
            except ValueError:
                fail(422, '负责人筛选值无效')
        else:
            parsed_owner = None
        items = [task(db, project_id, f"T-{r['pk']:03d}") for r in db.execute(
            'SELECT pk FROM tasks WHERE project_id=? ORDER BY pk DESC', (project_id,))]
        if cancelled == 'active':
            items = [item for item in items if not item['cancelled']]
        elif cancelled == 'only':
            items = [item for item in items if item['cancelled']]
        query = q.strip().casefold()
        if query:
            items = [item for item in items if query in ' '.join(str(item.get(k) or '') for k in
                ('id', 'title', 'description', 'requirement_id', 'owner_name')).casefold()]
        if status:
            items = [item for item in items if item['status'] == status]
        if owner_id == 'unassigned':
            items = [item for item in items if item['owner_id'] is None]
        elif owner_id:
            items = [item for item in items if item['owner_id'] == parsed_owner]
        return items

    @app.get('/api/projects/{project_id}/planning')
    def project_planning(project_id: int, actor=Depends(task_reader), db=Depends(database, scope='function')):
        return planning_snapshot(db, project_id,
            lambda pk: task(db, project_id, f'T-{pk:03d}'),
            lambda user_id: capacity(db, project_id, user_id))

    @app.get('/api/projects/{project_id}/tasks/{task_id}')
    def get_task(project_id: int, task_id: str, actor=Depends(task_reader), db=Depends(database, scope='function')):
        return task(db, project_id, task_id)

    @app.post('/api/projects/{project_id}/tasks', status_code=201)
    def create_task(project_id: int, body: TaskIn, actor=Depends(task_writer), db=Depends(database, scope='function')):
        if 'requirement.read' not in actor['permissions']:
            fail(403, '创建任务需要读取源需求的权限')
        requirement(db, project_id, body.requirement_id)
        check_owner(db, project_id, body.owner_id)
        check_milestone(db, project_id, body.milestone_id)
        stamp = now()
        pk = db.execute('''INSERT INTO tasks(project_id,requirement_pk,title,description,owner_id,due_date,sprint,milestone_id,
            created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (project_id, key(body.requirement_id, 'REQ'),
            body.title, body.description, body.owner_id, body.due_date.isoformat() if body.due_date else None,
            body.sprint, body.milestone_id, actor['id'], stamp, stamp)).lastrowid
        result = task(db, project_id, f'T-{pk:03d}')
        event(db, project_id, 'task', result['id'], 'created', actor['id'], None, result)
        return result

    @app.patch('/api/projects/{project_id}/tasks/{task_id}')
    def edit_task(project_id: int, task_id: str, body: TaskEdit, actor=Depends(task_writer), db=Depends(database, scope='function')):
        old = task(db, project_id, task_id)
        require_mutable_task(old)
        if body.version != old['version']:
            fail(409, '任务已被更新，请刷新后重试')
        if old['status'] == '已完成':
            fail(409, '已完成任务不可编辑，请先由管理员重开')
        check_owner(db, project_id, body.owner_id)
        check_milestone(db, project_id, body.milestone_id)
        db.execute('''UPDATE tasks SET title=?,description=?,owner_id=?,due_date=?,sprint=?,milestone_id=?,
            version=version+1,updated_at=? WHERE project_id=? AND pk=?''', (body.title, body.description, body.owner_id,
            body.due_date.isoformat() if body.due_date else None, body.sprint, body.milestone_id, now(),
            project_id, key(task_id, 'T')))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task', task_id, 'updated', actor['id'], old, result)
        return result

    @app.patch('/api/projects/{project_id}/tasks/{task_id}/status')
    def change_status(project_id: int, task_id: str, body: StatusIn, actor=Depends(task_writer), db=Depends(database, scope='function')):
        old = task(db, project_id, task_id)
        require_mutable_task(old)
        if body.version != old['version']:
            fail(409, '任务已被更新，请刷新后重试')
        transitions = {'待办': ['进行中'], '进行中': ['待办', '待验收'], '待验收': ['进行中', '已完成'], '已完成': []}
        if body.status not in transitions[old['status']]:
            fail(409, '不允许此状态转换')
        if body.status == '已完成':
            if actor['role'] != 'admin':
                fail(403, '仅管理员可最终验收')
            if not body.acceptance_confirmed:
                fail(422, '请确认关联验收条件已通过')
        backward = (old['status'], body.status) in [('进行中', '待办'), ('待验收', '进行中')]
        if backward and not body.reason.strip():
            fail(422, '退回原因必填')
        db.execute('UPDATE tasks SET status=?,version=version+1,updated_at=? WHERE project_id=? AND pk=?', (body.status, now(), project_id, key(task_id, 'T')))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task', task_id, 'accepted' if body.status == '已完成' else 'status_changed', actor['id'], old, result, body.reason.strip())
        return result

    @app.patch('/api/projects/{project_id}/tasks/{task_id}/source')
    def change_task_source(project_id: int, task_id: str, body: TaskSourceIn,
                           actor=Depends(task_writer), db=Depends(database, scope='function')):
        if 'requirement.read' not in actor['permissions']:
            fail(403, '变更来源需要读取需求的权限')
        old = task(db, project_id, task_id)
        require_mutable_task(old)
        if body.version != old['version']:
            fail(409, '任务已被更新，请刷新后重试')
        if old['status'] == '已完成':
            fail(409, '已完成任务不可修改来源，请先由管理员重开')
        source = requirement(db, project_id, body.requirement_id)
        if source['id'] == old['requirement_id']:
            fail(409, '任务已经关联此需求')
        db.execute('''UPDATE tasks SET requirement_pk=?,review_required=1,version=version+1,updated_at=?
            WHERE project_id=? AND pk=?''', (key(body.requirement_id, 'REQ'), now(), project_id, key(task_id, 'T')))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task', task_id, 'source_changed', actor['id'], old, result, body.reason)
        return result

    @app.post('/api/projects/{project_id}/tasks/{task_id}/dependencies', status_code=201)
    def add_dependency(project_id: int, task_id: str, body: DependencyIn,
                       actor=Depends(task_writer), db=Depends(database, scope='function')):
        current_pk = key(task_id, 'T')
        depends_pk = key(body.depends_on_id, 'T')
        current = task(db, project_id, task_id)
        prerequisite = task(db, project_id, body.depends_on_id)
        require_mutable_task(current)
        require_mutable_task(prerequisite)
        if current_pk == depends_pk:
            fail(422, '任务不能依赖自身')
        if db.execute('SELECT 1 FROM task_dependencies WHERE project_id=? AND task_pk=? AND depends_on_pk=?',
                      (project_id, current_pk, depends_pk)).fetchone():
            fail(409, '此依赖已存在')
        # If the prerequisite already reaches the current task, adding this edge creates a cycle.
        reachable = {current_pk}
        frontier = [current_pk]
        while frontier:
            node = frontier.pop()
            for row in db.execute('SELECT task_pk FROM task_dependencies WHERE project_id=? AND depends_on_pk=?',
                                  (project_id, node)):
                if row['task_pk'] not in reachable:
                    reachable.add(row['task_pk'])
                    frontier.append(row['task_pk'])
        if depends_pk in reachable:
            fail(422, '新增依赖会形成循环')
        stamp = now()
        db.execute('''INSERT INTO task_dependencies(project_id,task_pk,depends_on_pk,reason,created_by,created_at)
            VALUES(?,?,?,?,?,?)''', (project_id, current_pk, depends_pk, body.reason, actor['id'], stamp))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task_dependency', f'{task_id}:{body.depends_on_id}', 'dependency_added',
              actor['id'], None, {'task_id': task_id, 'depends_on_id': body.depends_on_id}, body.reason)
        return result

    @app.delete('/api/projects/{project_id}/tasks/{task_id}/dependencies/{depends_on_id}')
    def remove_dependency(project_id: int, task_id: str, depends_on_id: str, body: DependencyRemoveIn,
                          actor=Depends(task_writer), db=Depends(database, scope='function')):
        current_pk, depends_pk = key(task_id, 'T'), key(depends_on_id, 'T')
        current = task(db, project_id, task_id)
        require_mutable_task(current)
        row = db.execute('SELECT * FROM task_dependencies WHERE project_id=? AND task_pk=? AND depends_on_pk=?',
                         (project_id, current_pk, depends_pk)).fetchone()
        if not row:
            fail(404, '依赖关系不存在')
        db.execute('DELETE FROM task_dependencies WHERE project_id=? AND task_pk=? AND depends_on_pk=?',
                   (project_id, current_pk, depends_pk))
        event(db, project_id, 'task_dependency', f'{task_id}:{depends_on_id}', 'dependency_removed', actor['id'],
              dict(row), {'task_id': task_id, 'depends_on_id': depends_on_id, 'removed': True}, body.reason)
        return task(db, project_id, task_id)

    @app.patch('/api/projects/{project_id}/tasks/{task_id}/blocker')
    def set_blocker(project_id: int, task_id: str, body: BlockerIn,
                    actor=Depends(task_writer), db=Depends(database, scope='function')):
        old = task(db, project_id, task_id)
        require_mutable_task(old)
        if body.version != old['version']:
            fail(409, '任务已被更新，请刷新后重试')
        reason = body.reason.strip() if body.blocked else ''
        if body.blocked and not reason:
            fail(422, '阻塞原因必填')
        db.execute('UPDATE tasks SET manual_block_reason=?,version=version+1,updated_at=? WHERE project_id=? AND pk=?',
                   (reason, now(), project_id, key(task_id, 'T')))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task', task_id, 'blocked' if body.blocked else 'unblocked', actor['id'], old, result, body.reason)
        return result

    @app.patch('/api/projects/{project_id}/tasks/{task_id}/plan')
    def update_task_plan(project_id: int, task_id: str, body: TaskPlanIn,
                         actor=Depends(task_writer), db=Depends(database, scope='function')):
        old = task(db, project_id, task_id)
        require_mutable_task(old)
        if old['status'] == '已完成':
            fail(409, '已完成任务不可修改排期，请先由管理员重开')
        if body.version != old['version']:
            fail(409, '任务已被更新，请刷新后重试')
        db.execute('''UPDATE tasks SET estimated_hours=?,actual_hours=?,remaining_hours=?,planned_start=?,
            planned_end=?,plan_locked=?,required_skills_json=?,version=version+1,updated_at=? WHERE project_id=? AND pk=?''',
            (body.estimated_hours, body.actual_hours, body.remaining_hours,
             body.planned_start.isoformat() if body.planned_start else None,
             body.planned_end.isoformat() if body.planned_end else None, int(body.plan_locked),
             json.dumps(body.required_skills, ensure_ascii=False), now(),
             project_id, key(task_id, 'T')))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task', task_id, 'plan_updated', actor['id'], old, result, body.reason.strip())
        return result

    @app.patch('/api/projects/{project_id}/tasks/{task_id}/cancel')
    def cancel_task(project_id: int, task_id: str, body: TaskActionIn,
                    actor=Depends(admin), db=Depends(database, scope='function')):
        old = task(db, project_id, task_id)
        require_mutable_task(old)
        if body.version != old['version']:
            fail(409, '任务已被更新，请刷新后重试')
        stamp = now()
        db.execute('''UPDATE tasks SET cancelled_at=?,cancelled_by=?,cancel_reason=?,version=version+1,updated_at=?
            WHERE project_id=? AND pk=?''',
            (stamp, actor['id'], body.reason, stamp, project_id, key(task_id, 'T')))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task', task_id,
              'cancelled_completed' if old['status'] == '已完成' else 'cancelled',
              actor['id'], old, result, body.reason)
        return result

    @app.patch('/api/projects/{project_id}/tasks/{task_id}/reopen')
    def reopen_task(project_id: int, task_id: str, body: TaskActionIn,
                    actor=Depends(admin), db=Depends(database, scope='function')):
        old = task(db, project_id, task_id)
        require_mutable_task(old)
        if body.version != old['version']:
            fail(409, '任务已被更新，请刷新后重试')
        if old['status'] != '已完成':
            fail(409, '只有已完成任务可以重开')
        stamp = now()
        db.execute('''UPDATE tasks SET status='进行中',version=version+1,updated_at=?
            WHERE project_id=? AND pk=?''', (stamp, project_id, key(task_id, 'T')))
        result = task(db, project_id, task_id)
        event(db, project_id, 'task', task_id, 'reopened', actor['id'], old, result, body.reason)
        return result

    @app.get('/api/projects/{project_id}/tasks/{task_id}/history')
    def task_history(project_id: int, task_id: str, actor=Depends(history_reader),
                     db=Depends(database, scope='function')):
        current = task(db, project_id, task_id)
        rows = db.execute('''SELECT e.*,u.name actor_name FROM events e JOIN users u ON u.id=e.actor_id
            WHERE e.project_id=? AND ((e.entity_type='task' AND e.entity_id=?) OR
            (e.entity_type='task_dependency' AND (e.entity_id LIKE ? OR e.entity_id LIKE ?)))
            ORDER BY e.occurred_at DESC,e.id DESC''',
            (project_id, task_id, task_id + ':%', '%:' + task_id)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item['before'] = json.loads(item.pop('before_json')) if item['before_json'] else None
            item['after'] = json.loads(item.pop('after_json'))
            items.append(item)
        event_types = {item['event_type'] for item in items if item['entity_type'] == 'task'}
        gaps = []
        if 'created' not in event_types:
            gaps.append('缺少任务创建事件；未使用当前快照补造历史')
        if current['review_required'] and not event_types.intersection({'source_changed', 'source_requirement_changed'}):
            gaps.append('任务已标记源需求待复核，但没有可对应的源变更事件')
        return {'task_id': task_id, 'readonly': True, 'events': items, 'missing_records': gaps}

    @app.get('/api/projects/{project_id}/milestones')
    def milestones(project_id: int, actor=Depends(milestone_reader), db=Depends(database, scope='function')):
        return [milestone(db, project_id, row['id']) for row in db.execute(
            'SELECT id FROM milestones WHERE project_id=? ORDER BY target_date,id', (project_id,))]

    @app.post('/api/projects/{project_id}/milestones', status_code=201)
    def create_milestone(project_id: int, body: MilestoneIn, actor=Depends(milestone_writer),
                         db=Depends(database, scope='function')):
        stamp = now()
        try:
            milestone_id = db.execute('''INSERT INTO milestones(project_id,name,target_date,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?)''', (project_id, body.name, body.target_date.isoformat(), actor['id'], stamp, stamp)).lastrowid
        except sqlite3.IntegrityError:
            fail(409, '里程碑名称已存在')
        result = milestone(db, project_id, milestone_id)
        event(db, project_id, 'milestone', str(milestone_id), 'created', actor['id'], None, result)
        return result

    @app.patch('/api/projects/{project_id}/milestones/{milestone_id}')
    def edit_milestone(project_id: int, milestone_id: int, body: MilestoneEdit, actor=Depends(milestone_writer),
                       db=Depends(database, scope='function')):
        old = milestone(db, project_id, milestone_id)
        if body.version != old['version']:
            fail(409, '里程碑已被更新，请刷新后重试')
        try:
            db.execute('''UPDATE milestones SET name=?,target_date=?,version=version+1,updated_at=?
                WHERE project_id=? AND id=?''', (body.name, body.target_date.isoformat(), now(), project_id, milestone_id))
        except sqlite3.IntegrityError:
            fail(409, '里程碑名称已存在')
        result = milestone(db, project_id, milestone_id)
        event(db, project_id, 'milestone', str(milestone_id), 'updated', actor['id'], old, result)
        return result

    @app.get('/api/projects/{project_id}/milestones/{milestone_id}/tasks')
    def milestone_tasks(project_id: int, milestone_id: int, actor=Depends(milestone_reader),
                        db=Depends(database, scope='function')):
        milestone(db, project_id, milestone_id)
        return [task(db, project_id, f"T-{row['pk']:03d}") for row in db.execute(
            'SELECT pk FROM tasks WHERE project_id=? AND milestone_id=? ORDER BY pk DESC', (project_id, milestone_id))]

    @app.get('/api/projects/{project_id}/statistics/completion')
    def completion(project_id: int, q: str = '', status: str = '', owner_id: str = '',
                   cancelled: str = 'active',
                   actor=Depends(statistics_reader), db=Depends(database, scope='function')):
        if status and status not in ('待办', '进行中', '待验收', '已完成'):
            fail(422, '任务状态筛选值无效')
        if cancelled not in ('active', 'only', 'all'):
            fail(422, '取消状态筛选值无效')
        items = [task(db, project_id, f"T-{row['pk']:03d}") for row in db.execute(
            'SELECT pk FROM tasks WHERE project_id=? ORDER BY pk DESC', (project_id,))]
        query = q.strip().casefold()
        if query:
            items = [item for item in items if query in ' '.join(str(item.get(k) or '') for k in
                ('id', 'title', 'description', 'requirement_id', 'owner_name')).casefold()]
        if status:
            items = [item for item in items if item['status'] == status]
        if owner_id:
            if owner_id == 'unassigned':
                items = [item for item in items if item['owner_id'] is None]
            else:
                try:
                    parsed_owner = int(owner_id)
                    if parsed_owner <= 0:
                        raise ValueError
                except ValueError:
                    fail(422, '负责人筛选值无效')
                items = [item for item in items if item['owner_id'] == parsed_owner]
        active_items = [item for item in items if not item['cancelled']]
        cancelled_items = [item for item in items if item['cancelled']]
        counted_active = [] if cancelled == 'only' else active_items
        status_counts = {name: sum(item['status'] == name for item in counted_active) for name in ('待办', '进行中', '待验收', '已完成')}
        total = len(counted_active)
        completed = status_counts['已完成']
        result_total = len(cancelled_items) if cancelled == 'only' else len(active_items) + (len(cancelled_items) if cancelled == 'all' else 0)
        filters = {'q': q.strip(), 'status': status, 'owner_id': owner_id}
        if cancelled != 'active':
            filters['cancelled'] = cancelled
        week_start, week_end = current_natural_week()
        reopen_count = db.execute('''SELECT COUNT(*) FROM events WHERE project_id=? AND entity_type='task'
            AND event_type='reopened' AND occurred_at>=? AND occurred_at<?''',
            (project_id, week_start.astimezone(timezone.utc).isoformat(),
             week_end.astimezone(timezone.utc).isoformat())).fetchone()[0]
        return {'active_total': total, 'completed': completed,
                'completion_rate': round(completed * 100 / total, 1) if total else None,
                'status_counts': status_counts, 'cancelled_count': len(cancelled_items),
                'cancelled_completed_count': sum(item['status'] == '已完成' for item in cancelled_items),
                'result_total': result_total, 'filters': filters,
                'current_week': {'timezone': 'Asia/Shanghai', 'start': week_start.date().isoformat(),
                                 'end_exclusive': week_end.date().isoformat(), 'reopened_count': reopen_count}}

    @app.get('/api/projects/{project_id}/roles')
    def roles(project_id: int, actor=Depends(access), db=Depends(database, scope='function')):
        builtins = [
            {'key': key, 'id': None, 'name': name, 'description': description, 'builtin': True,
             'permissions': sorted(BUILTIN_PERMISSIONS[key]), 'version': None}
            for key, name, description in (
                ('admin', '管理员', '项目完整权限及保留敏感操作'),
                ('member', '成员', '需求与任务协作权限'),
                ('observer', '观察者', '项目只读权限'),
            )]
        custom = []
        for row in db.execute('SELECT * FROM custom_roles WHERE project_id=? ORDER BY id', (project_id,)):
            item = dict(row)
            item.update({'key': f"custom:{item['id']}", 'builtin': False,
                         'permissions': sorted(custom_permissions(db, item['id']))})
            custom.append(item)
        return builtins + custom

    @app.get('/api/projects/{project_id}/roles/permissions')
    def permission_catalog(project_id: int, actor=Depends(access)):
        return [{'id': permission, 'module': permission.split('.')[0], 'operation': permission.split('.')[1]}
                for permission in PERMISSIONS]

    @app.post('/api/projects/{project_id}/roles', status_code=201)
    def create_role(project_id: int, body: CustomRoleIn, actor=Depends(admin),
                    db=Depends(database, scope='function')):
        stamp = now()
        try:
            role_id = db.execute('''INSERT INTO custom_roles(project_id,name,description,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?)''', (project_id, body.name, body.description.strip(), actor['id'], stamp, stamp)).lastrowid
        except sqlite3.IntegrityError:
            fail(409, '角色名称已存在')
        result = {'id': role_id, 'key': f'custom:{role_id}', 'name': body.name,
                  'description': body.description.strip(), 'builtin': False, 'permissions': [], 'version': 1}
        event(db, project_id, 'role', str(role_id), 'created', actor['id'], None, result)
        return result

    @app.patch('/api/projects/{project_id}/roles/{role_id}')
    def edit_role(project_id: int, role_id: int, body: CustomRoleEdit, actor=Depends(admin),
                  db=Depends(database, scope='function')):
        row = db.execute('SELECT * FROM custom_roles WHERE project_id=? AND id=?', (project_id, role_id)).fetchone()
        if not row:
            fail(404, '自定义角色不存在')
        old = {**dict(row), 'permissions': sorted(custom_permissions(db, role_id))}
        if body.version != old['version']:
            fail(409, '角色配置已被更新，请刷新后重试')
        permissions = validate_permissions(body.permissions)
        try:
            db.execute('''UPDATE custom_roles SET name=?,description=?,version=version+1,updated_at=?
                WHERE project_id=? AND id=?''', (body.name, body.description.strip(), now(), project_id, role_id))
        except sqlite3.IntegrityError:
            fail(409, '角色名称已存在')
        db.execute('DELETE FROM role_permissions WHERE role_id=?', (role_id,))
        db.executemany('INSERT INTO role_permissions(role_id,permission) VALUES(?,?)',
                       [(role_id, permission) for permission in sorted(permissions)])
        row = db.execute('SELECT * FROM custom_roles WHERE project_id=? AND id=?', (project_id, role_id)).fetchone()
        result = {**dict(row), 'key': f'custom:{role_id}', 'builtin': False, 'permissions': sorted(permissions)}
        event(db, project_id, 'role', str(role_id), 'permissions_changed', actor['id'], old, result)
        return result

    return app


app = create_app()

