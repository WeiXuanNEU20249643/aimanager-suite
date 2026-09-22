"""AI integration, deterministic evidence, and human review records."""
from __future__ import annotations

import json
import math
import os
import re
import socket
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from statistics import median
from urllib import error, parse, request

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator
from typing import Annotated, Literal

from .planning import task_hours


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
EvidenceText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Priority = Literal['Must', 'Should', 'Could', "Won't"]
CAPABILITIES = (
    'prd_breakdown', 'progress_forecast', 'smart_schedule',
    'risk_analysis', 'quality_analysis', 'efficiency_analysis',
)
CAPABILITY_LABELS = {
    'prd_breakdown': 'AI需求拆解与估算',
    'progress_forecast': '进度预测',
    'smart_schedule': '智能排期',
    'risk_analysis': '风险预警',
    'quality_analysis': '质量分析',
    'efficiency_analysis': '效率优化',
}


class AIModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class BreakdownTask(AIModel):
    local_id: str = Field(pattern=r'^TASK-[A-Za-z0-9_-]{1,40}$', max_length=45)
    title: ShortText
    description: str = Field(default='', max_length=2000)
    estimate_hours: float = Field(gt=0, le=100000)
    required_skills: list[ShortText] = Field(default_factory=list, max_length=20)
    depends_on: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('required_skills', 'depends_on')
    @classmethod
    def unique_values(cls, values):
        normalized = [value.casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError('列表项目不能重复')
        return values


class BreakdownStory(AIModel):
    local_id: str = Field(pattern=r'^STORY-[A-Za-z0-9_-]{1,40}$', max_length=46)
    role: ShortText
    story: ShortText
    acceptance_criteria: list[LongText] = Field(min_length=1, max_length=20)
    source_paragraph: LongText
    priority: Priority = 'Must'
    tasks: list[BreakdownTask] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def acceptance_fits_requirement(self):
        if len('\n'.join(self.acceptance_criteria)) > 10000:
            raise ValueError('验收条件合并后超过需求字段上限')
        return self


class BreakdownOutput(AIModel):
    stories: list[BreakdownStory] = Field(default_factory=list, max_length=50)
    ambiguous_items: list[LongText] = Field(default_factory=list, max_length=50)
    unsupported_items: list[dict] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def valid_graph(self):
        story_ids = [item.local_id for item in self.stories]
        task_ids = [task.local_id for story in self.stories for task in story.tasks]
        if len(story_ids) != len(set(story_ids)) or len(task_ids) != len(set(task_ids)):
            raise ValueError('故事和任务临时编号必须唯一')
        task_set = set(task_ids)
        edges = {}
        for story in self.stories:
            for task in story.tasks:
                if task.local_id in task.depends_on:
                    raise ValueError('任务不能依赖自身')
                if any(item not in task_set for item in task.depends_on):
                    raise ValueError('任务依赖必须引用本次输出中的临时任务编号')
                edges[task.local_id] = task.depends_on
        visiting, visited = set(), set()
        def visit(task_id):
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError('任务建议存在循环依赖')
            visiting.add(task_id)
            for dependency in edges.get(task_id, []):
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)
        for task_id in task_ids:
            visit(task_id)
        return self


class ForecastExplanation(AIModel):
    summary: LongText
    factors: list[ShortText] = Field(min_length=1, max_length=20)
    confidence_limits: list[ShortText] = Field(default_factory=list, max_length=20)


class ScheduleAssignmentExplanation(AIModel):
    task_id: str = Field(pattern=r'^T-[0-9]{3,19}$')
    reason: LongText
    tradeoffs: list[ShortText] = Field(default_factory=list, max_length=20)


class ScheduleExplanation(AIModel):
    summary: LongText
    assignments: list[ScheduleAssignmentExplanation] = Field(default_factory=list, max_length=500)


class RiskAdvice(AIModel):
    risk_id: str = Field(pattern=r'^RISK-[A-Za-z0-9_-]{1,80}$', max_length=85)
    severity: Literal['high', 'medium', 'low']
    recommendation: LongText
    owner_id: int = Field(gt=0, le=9223372036854775807)
    next_check_date: date


class RiskAnalysis(AIModel):
    summary: LongText
    risks: list[RiskAdvice] = Field(default_factory=list, max_length=500)


class QualityIssue(AIModel):
    issue_id: str = Field(pattern=r'^QUALITY-[A-Za-z0-9_-]{1,80}$', max_length=88)
    artifact_type: Literal['code', 'document', 'test_report']
    file_name: ShortText
    location: ShortText
    category: ShortText
    title: ShortText
    evidence: EvidenceText
    impact: LongText
    recommendation: LongText
    task_kind: Literal['defect', 'improvement']


class QualityAnalysis(AIModel):
    summary: LongText
    issues: list[QualityIssue] = Field(default_factory=list, max_length=200)


class EfficiencyAdvice(AIModel):
    metric_key: str = Field(pattern=r'^[a-z][a-z0-9_]{1,80}$', max_length=81)
    metric_value: float = Field(ge=0, le=1000000000)
    bottleneck: LongText
    recommendation: LongText
    action_title: ShortText
    owner_id: int = Field(gt=0, le=9223372036854775807)
    due_date: date
    review_metric: ShortText


class EfficiencyAnalysis(AIModel):
    summary: LongText
    bottlenecks: list[EfficiencyAdvice] = Field(default_factory=list, max_length=50)


@dataclass
class AIServiceError(Exception):
    code: str
    message: str
    status_code: int

    def __str__(self):
        return self.message


def ai_settings():
    endpoint = os.environ.get('AIMANAGER_AI_ENDPOINT', '').strip()
    base_url = os.environ.get('AIMANAGER_AI_BASE_URL', '').strip()
    if not endpoint and base_url:
        endpoint = base_url.rstrip('/') + '/chat/completions'
    model_id = os.environ.get('AIMANAGER_AI_MODEL', '').strip()
    try:
        timeout = float(os.environ.get('AIMANAGER_AI_TIMEOUT_SECONDS', '30'))
    except ValueError:
        timeout = 30.0
    timeout = min(max(timeout, 0.1), 120.0)
    return {'endpoint': endpoint, 'model_id': model_id, 'timeout': timeout,
            'api_key': os.environ.get('AIMANAGER_AI_API_KEY', '')}


def public_ai_settings():
    settings = ai_settings()
    return {'configured': bool(settings['endpoint'] and settings['model_id']),
            'model_id': settings['model_id'] or None,
            'timeout_seconds': settings['timeout']}


def public_provider_url(value):
    if not value:
        return ''
    parsed = parse.urlsplit(value)
    host = parsed.hostname or ''
    if parsed.port:
        host += f':{parsed.port}'
    return parse.urlunsplit((parsed.scheme, host, parsed.path, '', ''))


def _content_from_response(payload):
    if isinstance(payload.get('output_text'), str):
        return payload['output_text']
    choices = payload.get('choices')
    if isinstance(choices, list) and choices:
        content = choices[0].get('message', {}).get('content')
        if isinstance(content, list):
            content = ''.join(item.get('text', '') for item in content if isinstance(item, dict))
        if isinstance(content, str):
            return content
    output = payload.get('output')
    if isinstance(output, list):
        chunks = []
        for item in output:
            for part in item.get('content', []) if isinstance(item, dict) else []:
                if isinstance(part, dict) and isinstance(part.get('text'), str):
                    chunks.append(part['text'])
        if chunks:
            return ''.join(chunks)
    raise AIServiceError('invalid_format', 'AI 返回格式错误，未找到结构化内容', 502)


def call_structured(capability, instructions, input_payload):
    settings = ai_settings()
    if not settings['endpoint'] or not settings['model_id']:
        raise AIServiceError('not_configured', 'AI 服务尚未在服务端配置', 503)
    body = {
        'model': settings['model_id'],
        'temperature': 0.1,
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': f'AIMANAGER_CAPABILITY={capability}\n{instructions}'},
            {'role': 'user', 'content': json.dumps(input_payload, ensure_ascii=False)},
        ],
    }
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if settings['api_key']:
        headers['Authorization'] = 'Bearer ' + settings['api_key']
    http_request = request.Request(settings['endpoint'], data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                                   headers=headers, method='POST')
    try:
        with request.urlopen(http_request, timeout=settings['timeout']) as response:
            raw = response.read(5_000_000)
    except error.HTTPError as exc:
        status = exc.code
        exc.close()
        if status == 429:
            raise AIServiceError('quota_limited', 'AI 服务额度不足或请求频率受限', 429) from exc
        raise AIServiceError('provider_error', 'AI 服务调用失败，请稍后重试', 502) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise AIServiceError('timeout', 'AI 服务响应超时，输入已保留', 504) from exc
    except (error.URLError, OSError) as exc:
        raise AIServiceError('unavailable', '无法连接 AI 服务，输入已保留', 503) from exc
    try:
        response_payload = json.loads(raw.decode('utf-8'))
        content = _content_from_response(response_payload).strip()
        content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content, flags=re.IGNORECASE)
        result = json.loads(content)
    except AIServiceError:
        raise
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AIServiceError('invalid_format', 'AI 返回格式错误，未写入业务数据', 502) from exc
    if not isinstance(result, dict):
        raise AIServiceError('invalid_format', 'AI 返回格式错误，结构化结果必须是对象', 502)
    return result, settings['model_id'], public_provider_url(settings['endpoint'])


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def save_run(db, project_id, capability, input_version, input_data, model_id, provider_url,
             actor_id, created_at, *, output=None, failure=None):
    status = 'failed' if failure else 'draft'
    run_id = db.execute('''INSERT INTO ai_runs(project_id,capability,input_version,input_json,model_id,
        provider_url,status,output_json,error_code,error_message,created_by,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (project_id, capability, input_version, _json(input_data), model_id, provider_url, status,
         _json(output) if output is not None else None, failure.code if failure else None,
         failure.message if failure else None, actor_id, created_at)).lastrowid
    return load_run(db, project_id, run_id)


def load_run(db, project_id, run_id):
    row = db.execute('''SELECT ar.*,creator.name created_by_name,decider.name decided_by_name
        FROM ai_runs ar JOIN users creator ON creator.id=ar.created_by
        LEFT JOIN users decider ON decider.id=ar.decided_by
        WHERE ar.project_id=? AND ar.id=?''', (project_id, run_id)).fetchone()
    if not row:
        return None
    item = dict(row)
    item['input'] = json.loads(item.pop('input_json'))
    original_json = item.pop('output_json')
    edited_json = item.pop('edited_output_json')
    original = json.loads(original_json) if original_json else None
    edited = json.loads(edited_json) if edited_json else None
    item['original_output'] = original
    item['edited_output'] = edited
    item['output'] = edited if edited is not None else original
    item['capability_label'] = CAPABILITY_LABELS[item['capability']]
    reviews = []
    for review in db.execute('''SELECT ar.*,u.name actor_name FROM ai_reviews ar JOIN users u ON u.id=ar.actor_id
        WHERE ar.project_id=? AND ar.run_id=? ORDER BY ar.id''', (project_id, run_id)):
        review_item = dict(review)
        review_output_json = review_item.pop('output_json')
        review_item['output'] = json.loads(review_output_json) if review_output_json else None
        reviews.append(review_item)
    item['reviews'] = reviews
    return item


def list_runs(db, project_id, limit=50):
    rows = db.execute('SELECT id FROM ai_runs WHERE project_id=? ORDER BY id DESC LIMIT ?',
                      (project_id, limit)).fetchall()
    return [load_run(db, project_id, row['id']) for row in rows]


def normalize_breakdown(raw, prd_text):
    try:
        output = BreakdownOutput.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise AIServiceError('invalid_format', 'AI 返回的故事、验收条件或任务结构不合法', 502) from exc
    normalized_prd = ' '.join(prd_text.split())
    sourced, unsupported = [], list(output['unsupported_items'])
    for story in output['stories']:
        if ' '.join(story['source_paragraph'].split()) not in normalized_prd:
            unsupported.append({'reason': '来源段落无法在提交的 PRD 中定位', 'suggestion': story})
        else:
            sourced.append(story)
    output['stories'] = sourced
    output['unsupported_items'] = unsupported
    return output


def validate_breakdown(output):
    try:
        return BreakdownOutput.model_validate(output).model_dump()
    except ValidationError as exc:
        raise AIServiceError('invalid_review', '修改后的拆解结果未通过结构校验', 422) from exc


def breakdown_prompt():
    return '''根据用户提交的 PRD 原文生成可审查草案，只输出 JSON。根对象字段为 stories、ambiguous_items、unsupported_items。
stories 中每项必须包含 local_id(STORY-开头)、role、story、acceptance_criteria(可测试字符串数组)、source_paragraph(PRD原文中的连续文本)、priority(Must/Should/Could/Won't)、tasks。
每个任务必须包含 local_id(TASK-开头且全局唯一)、title、description、estimate_hours(正数小时)、required_skills(字符串数组)、depends_on(引用本次输出任务local_id)。
不要补造来源；歧义放 ambiguous_items，无可定位来源的建议放 unsupported_items。依赖不得自依赖或成环。'''


def _parse_date(value):
    return date.fromisoformat(value) if value else None


def _next_workday(value):
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def _add_workdays(start, count):
    current = _next_workday(start)
    remaining = max(count - 1, 0)
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def forecast_calculation(db, project_id, task_loader, capacity_loader, as_of_date=None):
    as_of_date = as_of_date or datetime.now(timezone(timedelta(hours=8))).date()
    tasks = [task_loader(row['pk']) for row in db.execute(
        'SELECT pk FROM tasks WHERE project_id=? ORDER BY pk', (project_id,))]
    samples = []
    for item in tasks:
        estimated, actual = float(item['estimated_hours'] or 0), float(item['actual_hours'] or 0)
        if item['status'] == '已完成' and not item['cancelled'] and estimated > 0 and actual > 0:
            samples.append({'task_id': item['id'], 'title': item['title'], 'estimated_hours': estimated,
                            'actual_hours': actual, 'ratio': round(actual / estimated, 4)})
    calibration_applied = len(samples) >= 3
    factor = float(median([item['ratio'] for item in samples])) if calibration_applied else 1.0
    active = {int(item['id'].split('-')[1]): item for item in tasks
              if not item['cancelled'] and item['status'] != '已完成'}

    visiting, visited, order = set(), set(), []
    cycle = False
    def visit(pk):
        nonlocal cycle
        if pk in visited or cycle:
            return
        if pk in visiting:
            cycle = True
            return
        visiting.add(pk)
        for dependency in active[pk]['dependencies']:
            dep_pk = int(dependency['id'].split('-')[1])
            if dep_pk in active:
                visit(dep_pk)
        visiting.remove(pk)
        visited.add(pk)
        order.append(pk)
    for pk in sorted(active):
        visit(pk)

    conflicts = []
    if cycle:
        conflicts.append({'type': 'dependency_cycle', 'severity': 'error', 'message': '任务依赖存在循环，无法计算预测日期'})
    member_next, projected_end, calculations = {}, {}, []
    if not cycle:
        for pk in order:
            item = active[pk]
            if item['owner_id'] is None:
                conflicts.append({'task_id': item['id'], 'type': 'unassigned', 'severity': 'error',
                                  'message': '任务未分配负责人，无法纳入容量预测'})
                continue
            capacity = capacity_loader(item['owner_id'])
            weekly = capacity.get('weekly_capacity_hours')
            if weekly is None or weekly <= 0:
                conflicts.append({'task_id': item['id'], 'type': 'capacity_missing', 'severity': 'error',
                                  'message': '负责人缺少有效周容量'})
                continue
            ready = as_of_date
            unresolved = False
            for dependency in item['dependencies']:
                dep_pk = int(dependency['id'].split('-')[1])
                if dep_pk in projected_end:
                    ready = max(ready, projected_end[dep_pk] + timedelta(days=1))
                else:
                    dep = task_loader(dep_pk)
                    if dep['status'] == '已完成' and not dep['cancelled']:
                        continue
                    dep_end = _parse_date(dep['planned_end'])
                    if dep_end:
                        ready = max(ready, dep_end + timedelta(days=1))
                    else:
                        conflicts.append({'task_id': item['id'], 'related_task_id': dep['id'],
                                          'type': 'dependency_unscheduled', 'severity': 'error',
                                          'message': '未完成前置任务缺少可用计划日期'})
                        unresolved = True
            if unresolved:
                continue
            start = max(as_of_date, ready, member_next.get(item['owner_id'], as_of_date),
                        _parse_date(capacity.get('available_from')) or as_of_date)
            start = _next_workday(start)
            base_hours = task_hours(item)
            adjusted_hours = round(base_hours * factor, 2)
            duration = max(1, math.ceil(adjusted_hours / (weekly / 5)))
            end = _add_workdays(start, duration)
            available_to = _parse_date(capacity.get('available_to'))
            if available_to and end > available_to:
                conflicts.append({'task_id': item['id'], 'type': 'availability_exceeded', 'severity': 'error',
                                  'message': f'预计结束 {end.isoformat()} 超出负责人可用期 {available_to.isoformat()}'})
                continue
            projected_end[pk] = end
            member_next[item['owner_id']] = end + timedelta(days=1)
            calculations.append({'task_id': item['id'], 'owner_id': item['owner_id'],
                                 'owner_name': item['owner_name'], 'base_remaining_hours': round(base_hours, 2),
                                 'calibrated_remaining_hours': adjusted_hours, 'start': start.isoformat(),
                                 'end': end.isoformat(), 'dependency_ids': [x['id'] for x in item['dependencies']]})
    expected = max(projected_end.values()).isoformat() if projected_end else None
    return {'as_of_date': as_of_date.isoformat(), 'sample_count': len(samples), 'samples': samples,
            'calibration_applied': calibration_applied, 'median_actual_estimate_ratio': round(factor, 4),
            'calculation': '校准后剩余工时 = 剩余工时 × 实际/估算比中位数' if calibration_applied
                           else '有效历史少于3条，使用未校准剩余工时',
            'expected_completion_date': expected, 'tasks': calculations, 'conflicts': conflicts,
            'data_notice': None if calibration_applied else '历史不足3条，当前为未经历史校准的基准计划'}


def forecast_prompt():
    return '''你是项目进度解释助手。输入中的预计日期、样本、中位数、任务计算和冲突均由服务端确定性计算，不得修改或另造数据。
只输出 JSON，字段为 summary(说明预计完成日期)、factors(具体影响因素数组)、confidence_limits(限制条件数组)。必须引用输入证据；数据不足时明确说明未经历史校准。'''


def validate_forecast_explanation(raw):
    try:
        return ForecastExplanation.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise AIServiceError('invalid_format', 'AI 返回的进度解释结构不合法', 502) from exc


def schedule_calculation(db, project_id, task_loader, capacity_loader, start_date=None):
    start_date = start_date or datetime.now(timezone(timedelta(hours=8))).date()
    tasks = [task_loader(row['pk']) for row in db.execute(
        'SELECT pk FROM tasks WHERE project_id=? ORDER BY pk', (project_id,))]
    priorities = {row['pk']: row['priority'] or 'Must' for row in db.execute('''SELECT t.pk,r.priority
        FROM tasks t JOIN requirements r ON r.project_id=t.project_id AND r.pk=t.requirement_pk
        WHERE t.project_id=?''', (project_id,))}
    members = []
    for row in db.execute('''SELECT u.id,u.name,m.role FROM memberships m JOIN users u ON u.id=m.user_id
        WHERE m.project_id=? AND m.active=1 AND u.active=1 AND m.role<>'observer' ORDER BY u.id''', (project_id,)):
        cap = capacity_loader(row['id'])
        members.append({**dict(row), **cap})

    active = {int(item['id'].split('-')[1]): item for item in tasks if not item['cancelled']}
    movable = {pk for pk, item in active.items() if item['status'] == '待办' and not item['plan_locked']}
    preserved = [{
        'task_id': item['id'], 'title': item['title'], 'status': item['status'],
        'owner_id': item['owner_id'], 'owner_name': item['owner_name'],
        'planned_start': item['planned_start'], 'planned_end': item['planned_end'],
        'reason': '已完成任务不移动' if item['status'] == '已完成' else (
            '锁定任务不移动' if item['plan_locked'] else '进行中或待验收任务不移动'),
    } for pk, item in active.items() if pk not in movable]

    indegree = {pk: 0 for pk in movable}
    successors = {pk: [] for pk in movable}
    for pk in movable:
        for dependency in active[pk]['dependencies']:
            dep_pk = int(dependency['id'].split('-')[1])
            if dep_pk in movable:
                indegree[pk] += 1
                successors[dep_pk].append(pk)
    priority_order = {'Must': 0, 'Should': 1, 'Could': 2, "Won't": 3}
    def order_key(pk):
        item = active[pk]
        return (priority_order.get(priorities.get(pk), 9), item.get('due_date') or '9999-12-31', pk)
    ready = sorted((pk for pk, count in indegree.items() if count == 0), key=order_key)
    order = []
    while ready:
        pk = ready.pop(0)
        order.append(pk)
        for successor in successors[pk]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
                ready.sort(key=order_key)
    conflicts = []
    if len(order) != len(movable):
        conflicts.append({'type': 'dependency_cycle', 'severity': 'error', 'message': '任务依赖存在循环，未生成可应用排期'})

    member_next = {}
    for item in active.values():
        if item['owner_id'] is None or item['status'] == '已完成' or int(item['id'].split('-')[1]) in movable:
            continue
        end = _parse_date(item['planned_end'])
        if end and end >= start_date:
            member_next[item['owner_id']] = max(member_next.get(item['owner_id'], start_date), end + timedelta(days=1))
    proposed_end, proposals = {}, []
    for pk in order:
        item = active[pk]
        required = item.get('required_skills') or []
        required_keys = {skill.casefold() for skill in required}
        candidates = []
        for member in members:
            weekly = member.get('weekly_capacity_hours')
            skills = {skill.casefold() for skill in member.get('skill_tags', [])}
            if weekly and weekly > 0 and required_keys.issubset(skills):
                candidates.append(member)
        if not candidates:
            conflicts.append({'task_id': item['id'], 'type': 'skill_or_capacity_missing', 'severity': 'error',
                              'message': '没有同时满足技能要求和有效容量的成员', 'required_skills': required})
            continue
        current = next((member for member in candidates if member['id'] == item['owner_id']), None)
        owner = current or min(candidates, key=lambda member: (member_next.get(member['id'], start_date), member['id']))
        ready_date = start_date
        dependency_error = False
        for dependency in item['dependencies']:
            dep_pk = int(dependency['id'].split('-')[1])
            if dep_pk in proposed_end:
                ready_date = max(ready_date, proposed_end[dep_pk] + timedelta(days=1))
            else:
                dep = task_loader(dep_pk)
                if dep['status'] == '已完成' and not dep['cancelled']:
                    continue
                dep_end = _parse_date(dep['planned_end'])
                if not dep_end:
                    conflicts.append({'task_id': item['id'], 'related_task_id': dep['id'],
                                      'type': 'dependency_unscheduled', 'severity': 'error',
                                      'message': '未完成前置任务缺少计划结束日期'})
                    dependency_error = True
                else:
                    ready_date = max(ready_date, dep_end + timedelta(days=1))
        if dependency_error:
            continue
        available_from = _parse_date(owner.get('available_from')) or start_date
        task_start = _next_workday(max(start_date, ready_date, available_from,
                                           member_next.get(owner['id'], start_date)))
        weekly = float(owner['weekly_capacity_hours'])
        hours = task_hours(item)
        duration = max(1, math.ceil(hours / (weekly / 5)))
        task_end = _add_workdays(task_start, duration)
        available_to = _parse_date(owner.get('available_to'))
        if available_to and task_end > available_to:
            conflicts.append({'task_id': item['id'], 'type': 'availability_exceeded', 'severity': 'error',
                              'message': f'建议结束 {task_end.isoformat()} 超出成员可用期 {available_to.isoformat()}'})
            continue
        due = _parse_date(item.get('due_date'))
        if due and task_end > due:
            conflicts.append({'task_id': item['id'], 'type': 'due_date_exceeded', 'severity': 'warning',
                              'message': f'建议结束 {task_end.isoformat()} 晚于截止日 {due.isoformat()}'})
        proposal = {'task_id': item['id'], 'title': item['title'], 'priority': priorities.get(pk, 'Must'),
                    'hours': round(hours, 2), 'required_skills': required,
                    'dependency_ids': [dependency['id'] for dependency in item['dependencies']],
                    'before_owner_id': item['owner_id'], 'before_owner_name': item['owner_name'],
                    'after_owner_id': owner['id'], 'after_owner_name': owner['name'],
                    'before_start': item['planned_start'], 'before_end': item['planned_end'],
                    'after_start': task_start.isoformat(), 'after_end': task_end.isoformat()}
        proposals.append(proposal)
        proposed_end[pk] = task_end
        member_next[owner['id']] = task_end + timedelta(days=1)
    return {'start_date': start_date.isoformat(), 'proposals': proposals, 'preserved': preserved,
            'conflicts': conflicts, 'blocked': any(item['severity'] == 'error' for item in conflicts),
            'constraint_note': '按优先级、依赖、技能、成员可用期和周容量确定；不承诺全局最优'}


def schedule_prompt():
    return '''你是项目排期解释助手。输入中的任务建议、日期、负责人、冲突和保留项均由服务端确定性规则产生，不得修改。
只输出 JSON，字段为 summary 和 assignments。assignments 必须为每条 proposal 提供 task_id、reason、tradeoffs(字符串数组)，解释技能、容量、依赖、优先级或截止日取舍；不得声称全局最优。'''


def validate_schedule_explanation(raw, proposal_ids):
    try:
        output = ScheduleExplanation.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise AIServiceError('invalid_format', 'AI 返回的排期解释结构不合法', 502) from exc
    actual = [item['task_id'] for item in output['assignments']]
    if len(actual) != len(set(actual)) or set(actual) != set(proposal_ids):
        raise AIServiceError('invalid_format', 'AI 排期解释未覆盖全部建议任务', 502)
    return output


def latest_risk_thresholds(db, project_id):
    row = db.execute('''SELECT rtv.*,u.name changed_by_name
        FROM risk_threshold_versions rtv JOIN users u ON u.id=rtv.changed_by
        WHERE rtv.project_id=? ORDER BY rtv.version DESC LIMIT 1''', (project_id,)).fetchone()
    if not row:
        return {'version': 0, 'overload_percent': 100.0, 'blocked_workdays': 1.0,
                'changed_by': None, 'changed_by_name': None, 'changed_at': None,
                'reason': '系统初始阈值'}
    return dict(row)


def list_risk_thresholds(db, project_id, limit=20):
    return [dict(row) for row in db.execute('''SELECT rtv.*,u.name changed_by_name
        FROM risk_threshold_versions rtv JOIN users u ON u.id=rtv.changed_by
        WHERE rtv.project_id=? ORDER BY rtv.version DESC LIMIT ?''', (project_id, limit))]


def _parse_datetime(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _working_hours_between(start, end):
    if end <= start:
        return 0.0
    local_tz = timezone(timedelta(hours=8), name='Asia/Shanghai')
    cursor = start.astimezone(local_tz).date()
    end_date = end.astimezone(local_tz).date()
    total = 0.0
    while cursor <= end_date:
        if cursor.weekday() < 5:
            day_start = datetime.combine(cursor, datetime_time(9), local_tz)
            day_end = datetime.combine(cursor, datetime_time(17), local_tz)
            overlap_start = max(start.astimezone(local_tz), day_start)
            overlap_end = min(end.astimezone(local_tz), day_end)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds() / 3600
        cursor += timedelta(days=1)
    return round(total, 2)


def _workdays_late(start, end):
    if end <= start:
        return 0
    cursor = start + timedelta(days=1)
    result = 0
    while cursor <= end:
        if cursor.weekday() < 5:
            result += 1
        cursor += timedelta(days=1)
    return result


def risk_calculation(db, project_id, task_loader, capacity_loader, thresholds, as_of_date=None):
    local_tz = timezone(timedelta(hours=8), name='Asia/Shanghai')
    if as_of_date is None:
        as_of_at = datetime.now(local_tz)
        as_of_date = as_of_at.date()
    else:
        as_of_at = datetime.combine(as_of_date, datetime_time(23, 59, 59), local_tz)
    tasks = [task_loader(row['pk']) for row in db.execute(
        'SELECT pk FROM tasks WHERE project_id=? ORDER BY pk', (project_id,))]
    active = [item for item in tasks if not item['cancelled'] and item['status'] != '已完成']
    forecast = forecast_calculation(db, project_id, task_loader, capacity_loader, as_of_date)
    forecast_by_task = {item['task_id']: item for item in forecast['tasks']}
    missing_data = []
    risks = []

    remaining_by_owner = {}
    owner_names = {}
    for item in active:
        if item['owner_id'] is None:
            missing_data.append({'task_id': item['id'], 'field': 'owner_id', 'message': '任务未分配负责人'})
        else:
            remaining_by_owner[item['owner_id']] = remaining_by_owner.get(item['owner_id'], 0.0) + task_hours(item)
            owner_names[item['owner_id']] = item['owner_name']
        if not item.get('due_date'):
            missing_data.append({'task_id': item['id'], 'field': 'due_date', 'message': '任务缺少截止日'})

    for owner_id, remaining in sorted(remaining_by_owner.items()):
        member_capacity = capacity_loader(owner_id)
        weekly = member_capacity.get('weekly_capacity_hours')
        if weekly is None or weekly <= 0:
            missing_data.append({'owner_id': owner_id, 'owner_name': owner_names[owner_id],
                                 'field': 'weekly_capacity_hours', 'message': '成员缺少有效周容量'})
            continue
        load_percent = round(remaining * 100 / weekly, 2)
        if load_percent > thresholds['overload_percent']:
            risks.append({'risk_id': f'RISK-OVERLOAD-{owner_id}', 'type': 'overload',
                          'title': f'{owner_names[owner_id]} 当前剩余工作超过周容量',
                          'task_ids': [item['id'] for item in active if item['owner_id'] == owner_id],
                          'owner_id': owner_id, 'owner_name': owner_names[owner_id],
                          'metric_key': 'load_percent', 'metric_value': load_percent, 'unit': '%',
                          'threshold': thresholds['overload_percent'],
                          'evidence': f'剩余 {round(remaining, 2)}h / 周容量 {weekly}h = {load_percent}%'})

    for item in active:
        if item.get('manual_block_reason'):
            row = db.execute('''SELECT occurred_at FROM events WHERE project_id=? AND entity_type='task'
                AND entity_id=? AND event_type='blocked' ORDER BY id DESC LIMIT 1''',
                (project_id, item['id'])).fetchone()
            if not row:
                missing_data.append({'task_id': item['id'], 'field': 'blocked_at',
                                     'message': '任务有阻塞原因但缺少阻塞开始事件'})
            else:
                blocked_hours = _working_hours_between(_parse_datetime(row['occurred_at']), as_of_at)
                blocked_workdays = round(blocked_hours / 8, 2)
                if blocked_workdays > thresholds['blocked_workdays']:
                    risks.append({'risk_id': f"RISK-BLOCKED-{item['id'].split('-')[1]}",
                                  'type': 'blocked', 'title': f"{item['id']} 阻塞超过阈值",
                                  'task_ids': [item['id']], 'owner_id': item['owner_id'],
                                  'owner_name': item['owner_name'], 'metric_key': 'blocked_workdays',
                                  'metric_value': blocked_workdays, 'unit': '工作日',
                                  'threshold': thresholds['blocked_workdays'],
                                  'evidence': f"自 {row['occurred_at']} 起阻塞 {blocked_workdays} 个工作日：{item['manual_block_reason']}"})
        due_date = _parse_date(item.get('due_date'))
        if due_date and due_date < as_of_date:
            late_days = _workdays_late(due_date, as_of_date)
            risks.append({'risk_id': f"RISK-OVERDUE-{item['id'].split('-')[1]}",
                          'type': 'overdue', 'title': f"{item['id']} 已逾期",
                          'task_ids': [item['id']], 'owner_id': item['owner_id'],
                          'owner_name': item['owner_name'], 'metric_key': 'days_overdue',
                          'metric_value': float(late_days), 'unit': '工作日', 'threshold': 0,
                          'evidence': f'截止日 {due_date.isoformat()}，截至 {as_of_date.isoformat()} 逾期 {late_days} 个工作日'})
        predicted = forecast_by_task.get(item['id'])
        if due_date and predicted and _parse_date(predicted['end']) > due_date:
            late_days = _workdays_late(due_date, _parse_date(predicted['end']))
            risks.append({'risk_id': f"RISK-FORECAST-{item['id'].split('-')[1]}",
                          'type': 'forecast_late', 'title': f"{item['id']} 预测晚于截止日",
                          'task_ids': [item['id']], 'owner_id': item['owner_id'],
                          'owner_name': item['owner_name'], 'metric_key': 'forecast_late_days',
                          'metric_value': float(late_days), 'unit': '工作日', 'threshold': 0,
                          'evidence': f"预测结束 {predicted['end']}，截止日 {due_date.isoformat()}，相差 {late_days} 个工作日"})

    unique_missing = []
    seen_missing = set()
    for item in missing_data:
        marker = (item.get('task_id'), item.get('owner_id'), item['field'])
        if marker not in seen_missing:
            seen_missing.add(marker)
            unique_missing.append(item)
    return {'as_of_date': as_of_date.isoformat(), 'thresholds': thresholds,
            'risks': risks, 'missing_data': unique_missing,
            'forecast_conflicts': forecast['conflicts'],
            'rule_note': '负荷超过阈值、阻塞超过阈值、任务逾期或预测晚于截止日时触发'}


def risk_prompt():
    return '''你是项目风险分析助手。输入中的风险触发项、任务、指标、阈值和缺失数据由服务端确定性计算，不得增删或改写。
只输出 JSON，字段为 summary 和 risks。risks 必须逐条覆盖输入 evidence.risks，字段为 risk_id、severity(high/medium/low)、recommendation、owner_id、next_check_date(YYYY-MM-DD)。
建议必须引用对应证据，给出可执行措施；负责人必须来自输入 members，检查时间应合理。缺失数据应在 summary 中单列说明，不得把缺失数据补造成事实。'''


def validate_risk_analysis(raw, evidence, member_ids):
    try:
        output = RiskAnalysis.model_validate(raw).model_dump(mode='json')
    except ValidationError as exc:
        raise AIServiceError('invalid_format', 'AI 返回的风险分析结构不合法', 502) from exc
    expected = [item['risk_id'] for item in evidence['risks']]
    actual = [item['risk_id'] for item in output['risks']]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise AIServiceError('invalid_format', 'AI 风险建议未逐条覆盖服务端触发的风险', 502)
    if any(item['owner_id'] not in member_ids for item in output['risks']):
        raise AIServiceError('invalid_format', 'AI 风险建议包含无效负责人', 502)
    return output


def quality_prompt():
    return '''你是项目质量分析助手。输入包含人工选定的代码片段、需求/说明文档和测试报告，三类资料均带文件名、版本和内容范围。
只输出 JSON，字段为 summary 和 issues。每个 issue 字段为 issue_id(QUALITY-开头)、artifact_type(code/document/test_report)、file_name、location、category、title、evidence、impact、recommendation、task_kind(defect/improvement)。
代码检查缺陷与可维护性，文档检查完整性与一致性，测试报告检查失败项与覆盖缺口。evidence 必须逐字来自对应输入内容，location 必须可定位；不得把静态分析描述成实际运行测试，不得补造文件或结论。'''


def validate_quality_analysis(raw, artifacts):
    try:
        output = QualityAnalysis.model_validate(raw).model_dump(mode='json')
    except ValidationError as exc:
        raise AIServiceError('invalid_format', 'AI 返回的质量分析结构不合法', 502) from exc
    issue_ids = [item['issue_id'] for item in output['issues']]
    if len(issue_ids) != len(set(issue_ids)):
        raise AIServiceError('invalid_format', 'AI 质量问题编号重复', 502)
    sources = {(item['artifact_type'], item['file_name']): item for item in artifacts}
    for issue in output['issues']:
        source = sources.get((issue['artifact_type'], issue['file_name']))
        if not source:
            raise AIServiceError('invalid_format', 'AI 质量问题引用了未提交的文件', 502)
        normalized_content = ' '.join(source['content'].split())
        if ' '.join(issue['evidence'].split()) not in normalized_content:
            raise AIServiceError('invalid_format', 'AI 质量问题的依据无法在输入范围中定位', 502)
    return output


def _hours_between(start, end):
    return round(max(0.0, (end - start).total_seconds() / 3600), 2)


def efficiency_calculation(db, project_id, task_loader, capacity_loader, as_of_date=None):
    local_tz = timezone(timedelta(hours=8), name='Asia/Shanghai')
    if as_of_date is None:
        as_of_at = datetime.now(local_tz)
        as_of_date = as_of_at.date()
    else:
        as_of_at = datetime.combine(as_of_date, datetime_time(23, 59, 59), local_tz)
    tasks = [task_loader(row['pk']) for row in db.execute(
        'SELECT pk FROM tasks WHERE project_id=? ORDER BY pk', (project_id,))]
    records = []
    coverage_start = None
    for item in tasks:
        created = _parse_datetime(item['created_at'])
        if created > as_of_at:
            continue
        coverage_start = created if coverage_start is None else min(coverage_start, created)
        events = [dict(row) for row in db.execute('''SELECT event_type,occurred_at,after_json
            FROM events WHERE project_id=? AND entity_type='task' AND entity_id=?
            AND occurred_at<=? ORDER BY occurred_at,id''',
            (project_id, item['id'], as_of_at.astimezone(timezone.utc).isoformat()))]
        started_at = None
        completed_at = None
        reopened_count = 0
        blocked_started = None
        blocked_hours = 0.0
        for row in events:
            occurred = _parse_datetime(row['occurred_at'])
            after = json.loads(row['after_json']) if row['after_json'] else {}
            if started_at is None and after.get('status') == '进行中':
                started_at = occurred
            if after.get('status') == '已完成' or row['event_type'] == 'accepted':
                completed_at = occurred
            if row['event_type'] == 'reopened':
                reopened_count += 1
                completed_at = None
            if row['event_type'] == 'blocked':
                blocked_started = occurred
            elif row['event_type'] == 'unblocked' and blocked_started:
                blocked_hours += _working_hours_between(blocked_started, occurred)
                blocked_started = None
        if blocked_started:
            blocked_hours += _working_hours_between(blocked_started, as_of_at)
        wait_hours = _hours_between(created, started_at) if started_at else None
        cycle_hours = _hours_between(started_at, completed_at) if started_at and completed_at else None
        records.append({'task_id': item['id'], 'title': item['title'], 'owner_id': item['owner_id'],
                        'owner_name': item['owner_name'], 'created_at': created.isoformat(),
                        'started_at': started_at.isoformat() if started_at else None,
                        'completed_at': completed_at.isoformat() if completed_at else None,
                        'wait_hours': wait_hours, 'cycle_hours': cycle_hours,
                        'reopen_count': reopened_count, 'blocked_hours': round(blocked_hours, 2),
                        'status': item['status']})

    cycle_values = [item['cycle_hours'] for item in records if item['cycle_hours'] is not None]
    wait_values = [item['wait_hours'] for item in records if item['wait_hours'] is not None]
    reopened_total = sum(item['reopen_count'] for item in records)
    blocked_total = round(sum(item['blocked_hours'] for item in records), 2)
    load_values = []
    for row in db.execute('''SELECT u.id,u.name FROM memberships m JOIN users u ON u.id=m.user_id
        WHERE m.project_id=? AND m.active=1 AND u.active=1 AND m.role<>'observer' ORDER BY u.id''', (project_id,)):
        member_tasks = [item for item in tasks if item['owner_id'] == row['id'] and not item['cancelled']
                        and item['status'] != '已完成']
        weekly = capacity_loader(row['id']).get('weekly_capacity_hours')
        if weekly and weekly > 0:
            remaining = round(sum(task_hours(item) for item in member_tasks), 2)
            load_values.append({'owner_id': row['id'], 'owner_name': row['name'],
                                'remaining_hours': remaining, 'weekly_capacity_hours': weekly,
                                'load_percent': round(remaining * 100 / weekly, 2)})
    load_gap = round(max((item['load_percent'] for item in load_values), default=0)
                     - min((item['load_percent'] for item in load_values), default=0), 2)
    metrics = [
        {'key': 'average_cycle_hours', 'label': '平均周期',
         'value': round(sum(cycle_values) / len(cycle_values), 2) if cycle_values else 0,
         'unit': '小时', 'sample_count': len(cycle_values)},
        {'key': 'average_wait_hours', 'label': '平均等待',
         'value': round(sum(wait_values) / len(wait_values), 2) if wait_values else 0,
         'unit': '小时', 'sample_count': len(wait_values)},
        {'key': 'reopen_count', 'label': '返工次数', 'value': float(reopened_total),
         'unit': '次', 'sample_count': len(records)},
        {'key': 'blocked_hours', 'label': '阻塞时长', 'value': blocked_total,
         'unit': '工作小时', 'sample_count': sum(item['blocked_hours'] > 0 for item in records)},
        {'key': 'load_gap_percent', 'label': '分配负荷差异', 'value': load_gap,
         'unit': '百分点', 'sample_count': len(load_values)},
    ]
    sufficient = len(cycle_values) >= 3
    return {'as_of_date': as_of_date.isoformat(),
            'coverage_start': coverage_start.date().isoformat() if coverage_start else None,
            'coverage_end': as_of_date.isoformat(), 'task_records': records,
            'member_loads': load_values, 'metrics': metrics, 'data_sufficient': sufficient,
            'data_notice': None if sufficient else '至少需要3条含开始与完成时间的任务记录，当前不作确定性效率结论',
            'interpretation_rule': '指标用于识别流程、任务切分和分配瓶颈，不用于评价个人绩效'}


def efficiency_prompt():
    return '''你是项目流程效率分析助手。输入中的周期、等待、返工、阻塞、分配差异和参与记录均由服务端计算，不得修改。
只输出 JSON，字段为 summary 和 bottlenecks。每项字段为 metric_key、metric_value、bottleneck、recommendation、action_title、owner_id、due_date(YYYY-MM-DD)、review_metric。
必须引用输入 metrics；建议只能面向流程、任务切分或工作分配，不得评价个人绩效。若 data_sufficient 为 false，bottlenecks 必须为空，并在 summary 中说明数据不足。负责人必须来自输入 members。'''


def validate_efficiency_analysis(raw, evidence, member_ids):
    try:
        output = EfficiencyAnalysis.model_validate(raw).model_dump(mode='json')
    except ValidationError as exc:
        raise AIServiceError('invalid_format', 'AI 返回的效率分析结构不合法', 502) from exc
    if not evidence['data_sufficient'] and output['bottlenecks']:
        raise AIServiceError('invalid_format', '数据不足时不得生成确定性效率结论', 502)
    metrics = {item['key']: item['value'] for item in evidence['metrics']}
    keys = [item['metric_key'] for item in output['bottlenecks']]
    if len(keys) != len(set(keys)):
        raise AIServiceError('invalid_format', 'AI 效率建议重复引用同一指标', 502)
    for item in output['bottlenecks']:
        if item['metric_key'] not in metrics or abs(item['metric_value'] - metrics[item['metric_key']]) > 0.001:
            raise AIServiceError('invalid_format', 'AI 效率建议未引用可复算指标', 502)
        if item['owner_id'] not in member_ids:
            raise AIServiceError('invalid_format', 'AI 效率建议包含无效负责人', 502)
    return output


def validate_review_output(capability, output, original_output):
    if capability == 'prd_breakdown':
        return validate_breakdown(output)
    if capability == 'progress_forecast':
        if set(output) != {'evidence', 'explanation'} or output.get('evidence') != original_output.get('evidence'):
            raise AIServiceError('invalid_review', '进度预测的确定性计算依据不可编辑', 422)
        explanation = validate_forecast_explanation(output.get('explanation'))
        return {'evidence': original_output['evidence'], 'explanation': explanation}
    if capability == 'smart_schedule':
        if set(output) != {'plan', 'explanation'} or output.get('plan') != original_output.get('plan'):
            raise AIServiceError('invalid_review', '智能排期的约束计算结果不可直接编辑，请重新生成', 422)
        proposal_ids = [item['task_id'] for item in original_output['plan']['proposals']]
        explanation = validate_schedule_explanation(output.get('explanation'), proposal_ids)
        return {'plan': original_output['plan'], 'explanation': explanation}
    if capability == 'risk_analysis':
        if (set(output) != {'evidence', 'member_ids', 'analysis'}
                or output.get('evidence') != original_output.get('evidence')
                or output.get('member_ids') != original_output.get('member_ids')):
            raise AIServiceError('invalid_review', '风险指标和触发依据不可编辑，请重新生成', 422)
        member_ids = set(original_output.get('member_ids', []))
        analysis = validate_risk_analysis(output.get('analysis'), original_output['evidence'], member_ids)
        return {'evidence': original_output['evidence'], 'member_ids': sorted(member_ids), 'analysis': analysis}
    if capability == 'quality_analysis':
        if set(output) != {'analysis', 'artifacts'} or output.get('artifacts') != original_output.get('artifacts'):
            raise AIServiceError('invalid_review', '质量分析输出结构无效', 422)
        analysis = validate_quality_analysis(output.get('analysis'), original_output.get('artifacts', []))
        return {'analysis': analysis, 'artifacts': original_output.get('artifacts', [])}
    if capability == 'efficiency_analysis':
        if (set(output) != {'evidence', 'member_ids', 'analysis'}
                or output.get('evidence') != original_output.get('evidence')
                or output.get('member_ids') != original_output.get('member_ids')):
            raise AIServiceError('invalid_review', '效率指标和参与记录不可编辑，请重新生成', 422)
        member_ids = set(original_output.get('member_ids', []))
        analysis = validate_efficiency_analysis(output.get('analysis'), original_output['evidence'], member_ids)
        return {'evidence': original_output['evidence'], 'member_ids': sorted(member_ids), 'analysis': analysis}
    raise AIServiceError('invalid_capability', 'AI 能力类型无效', 422)
