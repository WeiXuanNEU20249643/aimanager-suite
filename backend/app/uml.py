"""Deterministic Sprint 4 UML mappings backed by structured project data."""
import json


def public_generation(row):
    if not row:
        return None
    item = dict(row)
    item['content'] = json.loads(item.pop('content_json'))
    item['warnings'] = json.loads(item.pop('warnings_json'))
    return item


def latest_generation(db, project_id, diagram_type, source_key):
    row = db.execute('''SELECT g.*,u.name generated_by_name FROM uml_generations g
        JOIN users u ON u.id=g.generated_by
        WHERE g.project_id=? AND g.diagram_type=? AND g.source_key=?
        ORDER BY g.version DESC LIMIT 1''', (project_id, diagram_type, source_key)).fetchone()
    return public_generation(row)


def save_generation(db, project_id, diagram_type, source_key, source_version,
                    content, warnings, actor_id, generated_at):
    version = db.execute('''SELECT COALESCE(MAX(version),0)+1 FROM uml_generations
        WHERE project_id=? AND diagram_type=? AND source_key=?''',
        (project_id, diagram_type, source_key)).fetchone()[0]
    generation_id = db.execute('''INSERT INTO uml_generations(project_id,diagram_type,source_key,
        source_version,version,content_json,warnings_json,generated_by,generated_at)
        VALUES(?,?,?,?,?,?,?,?,?)''', (project_id, diagram_type, source_key, source_version, version,
        json.dumps(content, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False),
        actor_id, generated_at)).lastrowid
    row = db.execute('''SELECT g.*,u.name generated_by_name FROM uml_generations g
        JOIN users u ON u.id=g.generated_by WHERE g.id=?''', (generation_id,)).fetchone()
    return public_generation(row)


def scenario(db, project_id, scenario_id):
    row = db.execute('''SELECT s.*,creator.name created_by_name,updater.name updated_by_name
        FROM uml_scenarios s JOIN users creator ON creator.id=s.created_by
        JOIN users updater ON updater.id=s.updated_by
        WHERE s.project_id=? AND s.id=?''', (project_id, scenario_id)).fetchone()
    if not row:
        return None
    item = dict(row)
    item['participants'] = json.loads(item.pop('participants_json'))
    item['messages'] = json.loads(item.pop('messages_json'))
    latest = latest_generation(db, project_id, 'sequence', f'scenario:{scenario_id}')
    item['latest_generation'] = latest
    item['generation_stale'] = bool(latest and latest['source_version'] != item['version'])
    return item


def scenarios(db, project_id):
    return [scenario(db, project_id, row['id']) for row in db.execute(
        'SELECT id FROM uml_scenarios WHERE project_id=? ORDER BY id', (project_id,))]


def build_use_case(db, project_id, requirement_loader, task_loader):
    warnings = []
    actors = []
    actor_keys = set()
    use_cases = []
    relation_keys = {}
    for row in db.execute('SELECT pk FROM requirements WHERE project_id=? ORDER BY pk', (project_id,)):
        source = requirement_loader(row['pk'])
        role = source.get('story_role', '').strip()
        task_rows = list(db.execute('''SELECT pk FROM tasks WHERE project_id=? AND requirement_pk=?
            ORDER BY pk''', (project_id, row['pk'])))
        linked_tasks = [task_loader(item['pk']) for item in task_rows]
        if not role:
            warnings.append({'code': 'missing_role', 'source_id': source['id'],
                'message': f"{source['id']} 未确认故事角色，已保留为未连接用例"})
        else:
            actor_key = role.casefold()
            if actor_key not in actor_keys:
                actor_keys.add(actor_key)
                actors.append({'id': f'actor-{len(actors) + 1}', 'name': role})
            relation_key = (actor_key, source['title'].casefold())
            if relation_key in relation_keys:
                warnings.append({'code': 'duplicate_relation', 'source_id': source['id'],
                    'related_source_id': relation_keys[relation_key],
                    'message': f"{source['id']} 与 {relation_keys[relation_key]} 的角色和用例名称重复"})
            else:
                relation_keys[relation_key] = source['id']
        if not linked_tasks:
            warnings.append({'code': 'missing_tasks', 'source_id': source['id'],
                'message': f"{source['id']} 尚无关联任务"})
        use_cases.append({'id': source['id'], 'name': source['title'], 'actor': role or None,
            'requirement_version': source['version'],
            'tasks': [{'id': item['id'], 'title': item['title'], 'version': item['version'],
                       'status': item['status'], 'cancelled': item['cancelled']}
                      for item in linked_tasks]})
    covered = [item for item in use_cases if item['actor'] and item['tasks']]
    if len(covered) < 2:
        warnings.append({'code': 'coverage_insufficient', 'source_id': None,
            'message': '至少需要两个同时具备已确认角色和关联任务的核心场景以完成覆盖检查'})
    return {'actors': actors, 'use_cases': use_cases,
            'coverage': {'covered_count': len(covered), 'source_count': len(use_cases),
                         'minimum_core_scenarios': 2,
                         'passed': len(covered) >= 2}}, warnings


def build_sequence(scenario_item, task_loader):
    participants = scenario_item['participants']
    positions = {name: index for index, name in enumerate(participants)}
    requirement_ids = []
    messages = []
    for index, source in enumerate(scenario_item['messages'], start=1):
        linked_task = task_loader(source['task_id'])
        if linked_task['requirement_id'] not in requirement_ids:
            requirement_ids.append(linked_task['requirement_id'])
        messages.append({'order': index, 'from_participant': source['from_participant'],
            'to_participant': source['to_participant'], 'from_index': positions[source['from_participant']],
            'to_index': positions[source['to_participant']], 'label': source['label'],
            'branch_condition': source.get('branch_condition', ''), 'task_id': linked_task['id'],
            'requirement_id': linked_task['requirement_id'], 'task_version': linked_task['version'],
            'cancelled': linked_task['cancelled']})
    return {'scenario_id': scenario_item['id'], 'name': scenario_item['name'],
        'description': scenario_item['description'], 'participants': participants,
        'messages': messages, 'requirement_ids': requirement_ids,
        'task_ids': list(dict.fromkeys(item['task_id'] for item in messages))}
