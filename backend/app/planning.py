import math
from datetime import date, datetime, timedelta, timezone


CHINA_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')


def plan_state(db, project_id):
    row = db.execute('''SELECT ps.version,ps.updated_at,u.name updated_by_name
        FROM project_plan_state ps LEFT JOIN users u ON u.id=ps.updated_by
        WHERE ps.project_id=?''', (project_id,)).fetchone()
    if not row:
        return {'version': 0, 'updated_at': None, 'updated_by_name': None}
    return dict(row)


def touch_plan_state(db, project_id, actor_id, stamp):
    db.execute('''INSERT INTO project_plan_state(project_id,version,updated_at,updated_by)
        VALUES(?,1,?,?) ON CONFLICT(project_id) DO UPDATE SET
        version=project_plan_state.version+1,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
        (project_id, stamp, actor_id))
    return db.execute('SELECT version FROM project_plan_state WHERE project_id=?', (project_id,)).fetchone()[0]


def task_hours(item):
    remaining = float(item.get('remaining_hours') or 0)
    if remaining > 0:
        return remaining
    return max(float(item.get('estimated_hours') or 0) - float(item.get('actual_hours') or 0), 0)


def impacted_task_pks(db, project_id, requirement_pk):
    direct = {row['pk'] for row in db.execute(
        'SELECT pk FROM tasks WHERE project_id=? AND requirement_pk=? AND cancelled_at IS NULL',
        (project_id, requirement_pk))}
    impacted = set(direct)
    frontier = list(direct)
    while frontier:
        predecessor = frontier.pop()
        for row in db.execute('''SELECT task_pk FROM task_dependencies
            WHERE project_id=? AND depends_on_pk=?''', (project_id, predecessor)):
            if row['task_pk'] not in impacted:
                impacted.add(row['task_pk'])
                frontier.append(row['task_pk'])
    return direct, impacted


def planning_impact(db, project_id, requirement_pk, task_loader):
    direct, impacted = impacted_task_pks(db, project_id, requirement_pk)
    items = [task_loader(pk) for pk in sorted(impacted)]
    items = [item for item in items if not item['cancelled']]
    movable, preserved = [], []
    for item in items:
        summary = {
            'id': item['id'], 'title': item['title'], 'status': item['status'],
            'owner_id': item['owner_id'], 'owner_name': item['owner_name'],
            'planned_start': item['planned_start'], 'planned_end': item['planned_end'],
            'due_date': item['due_date'], 'plan_locked': item['plan_locked'],
            'estimated_hours': item['estimated_hours'], 'remaining_hours': item['remaining_hours'],
            'version': item['version'], 'direct': int(item['id'].split('-')[1]) in direct,
        }
        if item['status'] == '待办' and not item['plan_locked']:
            movable.append(summary)
        else:
            reason = '已完成任务不移动' if item['status'] == '已完成' else (
                '锁定任务保留承诺日期' if item['plan_locked'] else '进行中或待验收任务保留承诺日期')
            preserved.append({**summary, 'preserve_reason': reason})
    return {'direct_task_count': len(direct), 'impacted_task_count': len(items),
            'movable': movable, 'preserved': preserved}


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


def calculate_replan(db, project_id, requirement_pk, task_loader, capacity_loader, base_date=None):
    direct, impacted = impacted_task_pks(db, project_id, requirement_pk)
    all_items = {pk: task_loader(pk) for pk in impacted}
    movable = {pk for pk, item in all_items.items()
               if not item['cancelled'] and item['status'] == '待办' and not item['plan_locked']}
    preserved = {pk for pk in impacted if pk not in movable and not all_items[pk]['cancelled']}
    base_date = base_date or datetime.now(CHINA_TZ).date()

    order, visiting, visited = [], set(), set()
    def visit(pk):
        if pk in visited:
            return
        if pk in visiting:
            raise ValueError('任务依赖存在循环')
        visiting.add(pk)
        for row in db.execute('''SELECT depends_on_pk FROM task_dependencies
            WHERE project_id=? AND task_pk=? ORDER BY depends_on_pk''', (project_id, pk)):
            if row['depends_on_pk'] in movable:
                visit(row['depends_on_pk'])
        visiting.remove(pk)
        visited.add(pk)
        order.append(pk)
    for pk in sorted(movable):
        visit(pk)

    member_next = {}
    for row in db.execute('''SELECT pk,owner_id,planned_end FROM tasks
        WHERE project_id=? AND owner_id IS NOT NULL AND cancelled_at IS NULL
        AND status<>'已完成' AND planned_end IS NOT NULL''', (project_id,)):
        if row['pk'] in movable:
            continue
        end = _parse_date(row['planned_end'])
        if end and end >= base_date:
            member_next[row['owner_id']] = max(member_next.get(row['owner_id'], base_date), end + timedelta(days=1))

    proposals, conflicts, proposed_end = [], [], {}
    for pk in order:
        item = all_items[pk]
        if item['owner_id'] is None:
            conflicts.append({'task_id': item['id'], 'severity': 'error', 'type': 'unassigned',
                              'message': '任务未分配负责人，无法按成员容量排期'})
            continue
        member_capacity = capacity_loader(item['owner_id'])
        weekly = member_capacity.get('weekly_capacity_hours')
        if weekly is None or weekly <= 0:
            conflicts.append({'task_id': item['id'], 'severity': 'error', 'type': 'capacity_missing',
                              'message': '负责人未配置有效每周容量'})
            continue
        dependency_ready = base_date
        dependency_error = False
        for dependency in item['dependencies']:
            dep_pk = int(dependency['id'].split('-')[1])
            if dep_pk in proposed_end:
                dependency_ready = max(dependency_ready, proposed_end[dep_pk] + timedelta(days=1))
            else:
                dep = task_loader(dep_pk)
                dep_end = _parse_date(dep['planned_end'])
                if dep['status'] == '已完成' and not dep['cancelled']:
                    continue
                if not dep_end:
                    conflicts.append({'task_id': item['id'], 'severity': 'error', 'type': 'dependency_unscheduled',
                                      'related_task_id': dep['id'], 'message': '未完成的前置任务缺少计划结束日期'})
                    dependency_error = True
                else:
                    dependency_ready = max(dependency_ready, dep_end + timedelta(days=1))
        if dependency_error:
            continue
        available_from = _parse_date(member_capacity.get('available_from')) or base_date
        start = max(base_date, available_from, dependency_ready, member_next.get(item['owner_id'], base_date))
        start = _next_workday(start)
        daily_hours = weekly / 5
        duration = max(1, math.ceil(task_hours(item) / daily_hours)) if daily_hours else 1
        end = _add_workdays(start, duration)
        available_to = _parse_date(member_capacity.get('available_to'))
        if available_to and end > available_to:
            conflicts.append({'task_id': item['id'], 'severity': 'error', 'type': 'availability_exceeded',
                              'message': f'计划结束 {end.isoformat()} 超出负责人可用期 {available_to.isoformat()}'})
            continue
        due_date = _parse_date(item.get('due_date'))
        if due_date and end > due_date:
            conflicts.append({'task_id': item['id'], 'severity': 'warning', 'type': 'due_date_exceeded',
                              'message': f'计划结束 {end.isoformat()} 超出截止日 {due_date.isoformat()}'})
        proposals.append({'task_id': item['id'], 'pk': pk, 'before_start': item['planned_start'],
                          'before_end': item['planned_end'], 'after_start': start.isoformat(),
                          'after_end': end.isoformat(), 'hours': task_hours(item),
                          'direct': pk in direct, 'before': item})
        proposed_end[pk] = end
        member_next[item['owner_id']] = end + timedelta(days=1)

    for pk in sorted(preserved):
        item = all_items[pk]
        start = _parse_date(item['planned_start'])
        for dependency in item['dependencies']:
            dep_pk = int(dependency['id'].split('-')[1])
            dep_end = proposed_end.get(dep_pk) or _parse_date(task_loader(dep_pk)['planned_end'])
            if start and dep_end and start <= dep_end:
                conflicts.append({'task_id': item['id'], 'severity': 'warning', 'type': 'locked_dependency_conflict',
                                  'related_task_id': dependency['id'],
                                  'message': '保留任务的承诺日期与前置任务重排结果冲突，需人工处理'})
    return {'direct': direct, 'impacted': impacted, 'proposals': proposals, 'conflicts': conflicts,
            'blocked': any(item['severity'] == 'error' for item in conflicts)}


def planning_snapshot(db, project_id, task_loader, capacity_loader):
    all_tasks = [task_loader(row['pk']) for row in db.execute(
        'SELECT pk FROM tasks WHERE project_id=? ORDER BY pk', (project_id,))]
    tasks = [item for item in all_tasks if not item['cancelled']]
    scheduled = [item for item in tasks if item['planned_start'] and item['planned_end']]
    starts = [_parse_date(item['planned_start']) for item in scheduled]
    ends = [_parse_date(item['planned_end']) for item in scheduled]
    horizon_start = min(starts) if starts else None
    horizon_end = max(ends) if ends else None
    horizon_days = (horizon_end - horizon_start).days + 1 if horizon_start and horizon_end else 7

    rows = db.execute('''SELECT u.id,u.name,m.active,m.role,cr.name custom_role_name
        FROM users u JOIN memberships m ON m.user_id=u.id AND m.project_id=?
        LEFT JOIN custom_roles cr ON cr.id=m.custom_role_id AND cr.project_id=m.project_id
        WHERE u.active=1 ORDER BY m.active DESC,u.id''', (project_id,)).fetchall()
    members = {}
    for row in rows:
        item = dict(row)
        item['active'] = bool(item['active'])
        item['role_name'] = item['custom_role_name'] or {'admin': '管理员', 'member': '成员', 'observer': '观察者'}[item['role']]
        members[item['id']] = item
    for item in tasks:
        if item['owner_id'] and item['owner_id'] not in members:
            members[item['owner_id']] = {'id': item['owner_id'], 'name': item['owner_name'] or '已移除成员',
                'active': False, 'role': None, 'role_name': '已移除'}
    result_members = []
    for member in members.values():
        assigned = [item for item in tasks if item['owner_id'] == member['id'] and item['status'] != '已完成']
        workload = round(sum(task_hours(item) for item in assigned), 2)
        cap = capacity_loader(member['id'])
        weekly = cap.get('weekly_capacity_hours')
        capacity_hours = None if weekly is None else round(weekly * horizon_days / 7, 2)
        load_percent = round(workload * 100 / capacity_hours, 1) if capacity_hours else None
        result_members.append({**member, **cap, 'task_count': len(assigned), 'workload_hours': workload,
            'capacity_hours': capacity_hours, 'load_percent': load_percent,
            'overloaded': load_percent is not None and load_percent > 100})
    unassigned = [item for item in tasks if item['owner_id'] is None and item['status'] != '已完成']
    return {
        'plan': plan_state(db, project_id),
        'horizon': {'start': horizon_start.isoformat() if horizon_start else None,
                    'end': horizon_end.isoformat() if horizon_end else None,
                    'days': horizon_days},
        'tasks': tasks,
        'unscheduled_task_ids': [item['id'] for item in tasks if not item['planned_start'] or not item['planned_end']],
        'cancelled_count': len(all_tasks) - len(tasks),
        'members': result_members,
        'unassigned': {'task_count': len(unassigned), 'workload_hours': round(sum(task_hours(item) for item in unassigned), 2)},
    }
