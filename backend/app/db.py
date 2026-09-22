"""Versioned, additive SQLite schema. No automatic business/demo data."""
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / 'data' / 'aimanager.sqlite3'


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path=None):
    target = Path(path or os.environ.get('AIMANAGER_DB', DEFAULT_DB))
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=15, check_same_thread=False, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def migrate(path=None):
    with connect(path) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > 7:
            raise RuntimeError('Database schema is newer than this application')
        if version == 0:
            db.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
            CREATE TABLE memberships (
                project_id INTEGER NOT NULL REFERENCES projects(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                role TEXT NOT NULL CHECK(role IN ('admin','member','observer')),
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(project_id,user_id)
            );
            CREATE TABLE sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at REAL NOT NULL
            );
            CREATE TABLE requirements (
                pk INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
                title TEXT NOT NULL, description TEXT NOT NULL, source TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                UNIQUE(project_id,pk)
            );
            CREATE TABLE tasks (
                pk INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
                requirement_pk INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                owner_id INTEGER REFERENCES users(id), due_date TEXT,
                sprint TEXT NOT NULL CHECK(sprint IN ('S1','S2','S3','S4','S5','S6')),
                status TEXT NOT NULL DEFAULT '待办' CHECK(status IN ('待办','进行中','待验收','已完成')),
                version INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id,requirement_pk) REFERENCES requirements(project_id,pk)
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
                entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, event_type TEXT NOT NULL,
                actor_id INTEGER NOT NULL REFERENCES users(id), occurred_at TEXT NOT NULL,
                before_json TEXT, after_json TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                operation_id TEXT UNIQUE NOT NULL
            );
            CREATE INDEX tasks_project ON tasks(project_id);
            CREATE INDEX requirements_project ON requirements(project_id);
            CREATE INDEX events_entity ON events(project_id,entity_type,entity_id);
            CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'Events are append-only'); END;
            CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'Events are append-only'); END;
            PRAGMA user_version=1;
            COMMIT;
            ''')
            version = 1
        if version == 1:
            db.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE custom_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id,name),
                UNIQUE(project_id,id)
            );
            CREATE TABLE role_permissions (
                role_id INTEGER NOT NULL REFERENCES custom_roles(id) ON DELETE CASCADE,
                permission TEXT NOT NULL,
                PRIMARY KEY(role_id,permission)
            );
            ALTER TABLE memberships ADD COLUMN custom_role_id INTEGER REFERENCES custom_roles(id);

            ALTER TABLE requirements ADD COLUMN priority TEXT CHECK(priority IN ('Must','Should','Could','Won''t'));
            ALTER TABLE requirements ADD COLUMN acceptance_criteria TEXT;
            CREATE TABLE requirement_versions (
                project_id INTEGER NOT NULL REFERENCES projects(id),
                requirement_pk INTEGER NOT NULL,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT NOT NULL,
                priority TEXT,
                acceptance_criteria TEXT,
                changed_by INTEGER NOT NULL REFERENCES users(id),
                changed_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY(project_id,requirement_pk,version),
                FOREIGN KEY(project_id,requirement_pk) REFERENCES requirements(project_id,pk)
            );

            CREATE TABLE milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL,
                target_date TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id,name),
                UNIQUE(project_id,id)
            );
            ALTER TABLE tasks ADD COLUMN milestone_id INTEGER REFERENCES milestones(id);
            ALTER TABLE tasks ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE tasks ADD COLUMN manual_block_reason TEXT NOT NULL DEFAULT '';
            ALTER TABLE tasks ADD COLUMN cancelled_at TEXT;
            ALTER TABLE tasks ADD COLUMN cancelled_by INTEGER REFERENCES users(id);
            ALTER TABLE tasks ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT '';

            CREATE UNIQUE INDEX tasks_project_pk ON tasks(project_id,pk);
            CREATE TABLE task_dependencies (
                project_id INTEGER NOT NULL REFERENCES projects(id),
                task_pk INTEGER NOT NULL,
                depends_on_pk INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id,task_pk,depends_on_pk),
                FOREIGN KEY(project_id,task_pk) REFERENCES tasks(project_id,pk),
                FOREIGN KEY(project_id,depends_on_pk) REFERENCES tasks(project_id,pk),
                CHECK(task_pk<>depends_on_pk)
            );
            CREATE INDEX task_dependencies_target ON task_dependencies(project_id,depends_on_pk);
            CREATE INDEX requirements_priority ON requirements(project_id,priority);
            CREATE INDEX tasks_milestone ON tasks(project_id,milestone_id);
            PRAGMA user_version=2;
            COMMIT;
            ''')
            version = 2
        if version == 2:
            db.executescript('''
            BEGIN IMMEDIATE;
            ALTER TABLE tasks ADD COLUMN estimated_hours REAL NOT NULL DEFAULT 0 CHECK(estimated_hours>=0);
            ALTER TABLE tasks ADD COLUMN actual_hours REAL NOT NULL DEFAULT 0 CHECK(actual_hours>=0);
            ALTER TABLE tasks ADD COLUMN remaining_hours REAL NOT NULL DEFAULT 0 CHECK(remaining_hours>=0);
            ALTER TABLE tasks ADD COLUMN planned_start TEXT;
            ALTER TABLE tasks ADD COLUMN planned_end TEXT;
            ALTER TABLE tasks ADD COLUMN plan_locked INTEGER NOT NULL DEFAULT 0 CHECK(plan_locked IN (0,1));

            CREATE TABLE member_capacities (
                project_id INTEGER NOT NULL REFERENCES projects(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                weekly_capacity_hours REAL NOT NULL CHECK(weekly_capacity_hours>=0 AND weekly_capacity_hours<=168),
                available_from TEXT,
                available_to TEXT,
                skill_tags_json TEXT NOT NULL DEFAULT '[]',
                version INTEGER NOT NULL DEFAULT 1,
                updated_by INTEGER NOT NULL REFERENCES users(id),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project_id,user_id)
            );
            CREATE INDEX member_capacities_project ON member_capacities(project_id);
            CREATE INDEX tasks_plan_dates ON tasks(project_id,planned_start,planned_end);
            PRAGMA user_version=3;
            COMMIT;
            ''')
            version = 3
        if version == 3:
            db.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE project_plan_state (
                project_id INTEGER PRIMARY KEY REFERENCES projects(id),
                version INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                updated_by INTEGER REFERENCES users(id)
            );
            CREATE TABLE plan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                plan_version INTEGER NOT NULL,
                requirement_pk INTEGER NOT NULL,
                requirement_version INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('applied','blocked')),
                changes_json TEXT NOT NULL,
                conflicts_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                triggered_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                UNIQUE(project_id,plan_version),
                FOREIGN KEY(project_id,requirement_pk) REFERENCES requirements(project_id,pk)
            );
            CREATE INDEX plan_runs_requirement ON plan_runs(project_id,requirement_pk,id DESC);
            PRAGMA user_version=4;
            COMMIT;
            ''')
            version = 4
        if version == 4:
            db.executescript('''
            BEGIN IMMEDIATE;
            ALTER TABLE requirements ADD COLUMN story_role TEXT NOT NULL DEFAULT '';
            ALTER TABLE requirement_versions ADD COLUMN story_role TEXT NOT NULL DEFAULT '';

            CREATE TABLE uml_scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                participants_json TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                updated_by INTEGER NOT NULL REFERENCES users(id),
                updated_at TEXT NOT NULL,
                UNIQUE(project_id,name),
                UNIQUE(project_id,id)
            );
            CREATE TABLE uml_generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                diagram_type TEXT NOT NULL CHECK(diagram_type IN ('use_case','sequence')),
                source_key TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                content_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                generated_by INTEGER NOT NULL REFERENCES users(id),
                generated_at TEXT NOT NULL,
                UNIQUE(project_id,diagram_type,source_key,version)
            );
            CREATE INDEX uml_scenarios_project ON uml_scenarios(project_id,id);
            CREATE INDEX uml_generations_latest ON uml_generations(project_id,diagram_type,source_key,version DESC);
            CREATE TRIGGER uml_generations_no_update BEFORE UPDATE ON uml_generations
                BEGIN SELECT RAISE(ABORT,'UML generations are append-only'); END;
            CREATE TRIGGER uml_generations_no_delete BEFORE DELETE ON uml_generations
                BEGIN SELECT RAISE(ABORT,'UML generations are append-only'); END;
            PRAGMA user_version=5;
            COMMIT;
            ''')
            version = 5
        if version == 5:
            db.executescript('''
            BEGIN IMMEDIATE;
            ALTER TABLE tasks ADD COLUMN required_skills_json TEXT NOT NULL DEFAULT '[]';

            CREATE TABLE ai_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                capability TEXT NOT NULL CHECK(capability IN ('prd_breakdown','progress_forecast','smart_schedule','risk_analysis','quality_analysis','efficiency_analysis')),
                input_version INTEGER NOT NULL,
                input_json TEXT NOT NULL,
                model_id TEXT NOT NULL,
                provider_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('draft','applied','rejected','failed')),
                output_json TEXT,
                edited_output_json TEXT,
                error_code TEXT,
                error_message TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                decided_by INTEGER REFERENCES users(id),
                decided_at TEXT,
                decision_reason TEXT NOT NULL DEFAULT '',
                applied_operation_id TEXT,
                UNIQUE(project_id,id),
                UNIQUE(project_id,applied_operation_id)
            );
            CREATE INDEX ai_runs_project ON ai_runs(project_id,id DESC);
            CREATE INDEX ai_runs_status ON ai_runs(project_id,status,capability);
            CREATE TABLE ai_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('edited','applied','rejected')),
                output_json TEXT,
                reason TEXT NOT NULL,
                operation_id TEXT,
                actor_id INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id,run_id) REFERENCES ai_runs(project_id,id)
            );
            CREATE INDEX ai_reviews_run ON ai_reviews(project_id,run_id,id);
            CREATE TRIGGER ai_reviews_no_update BEFORE UPDATE ON ai_reviews
                BEGIN SELECT RAISE(ABORT,'AI reviews are append-only'); END;
            CREATE TRIGGER ai_reviews_no_delete BEFORE DELETE ON ai_reviews
                BEGIN SELECT RAISE(ABORT,'AI reviews are append-only'); END;
            PRAGMA user_version=6;
            COMMIT;
            ''')
            version = 6
        if version == 6:
            # SQLite cannot widen a CHECK constraint in-place. Rebuild the two
            # AI tables while foreign-key enforcement is temporarily disabled,
            # then validate every restored relationship before returning.
            db.commit()
            db.execute('PRAGMA foreign_keys=OFF')
            try:
                db.executescript('''
                BEGIN IMMEDIATE;
                DROP TRIGGER ai_reviews_no_update;
                DROP TRIGGER ai_reviews_no_delete;
                DROP INDEX ai_reviews_run;
                DROP INDEX ai_runs_project;
                DROP INDEX ai_runs_status;
                ALTER TABLE ai_reviews RENAME TO ai_reviews_v6;
                ALTER TABLE ai_runs RENAME TO ai_runs_v6;

                CREATE TABLE ai_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    capability TEXT NOT NULL CHECK(capability IN (
                        'prd_breakdown','progress_forecast','smart_schedule',
                        'risk_analysis','quality_analysis','efficiency_analysis'
                    )),
                    input_version INTEGER NOT NULL,
                    input_json TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    provider_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('draft','applied','rejected','failed')),
                    output_json TEXT,
                    edited_output_json TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    decided_by INTEGER REFERENCES users(id),
                    decided_at TEXT,
                    decision_reason TEXT NOT NULL DEFAULT '',
                    applied_operation_id TEXT,
                    UNIQUE(project_id,id),
                    UNIQUE(project_id,applied_operation_id)
                );
                INSERT INTO ai_runs SELECT * FROM ai_runs_v6;
                CREATE INDEX ai_runs_project ON ai_runs(project_id,id DESC);
                CREATE INDEX ai_runs_status ON ai_runs(project_id,status,capability);

                CREATE TABLE ai_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    run_id INTEGER NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('edited','applied','rejected')),
                    output_json TEXT,
                    reason TEXT NOT NULL,
                    operation_id TEXT,
                    actor_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id,run_id) REFERENCES ai_runs(project_id,id)
                );
                INSERT INTO ai_reviews SELECT * FROM ai_reviews_v6;
                CREATE INDEX ai_reviews_run ON ai_reviews(project_id,run_id,id);
                CREATE TRIGGER ai_reviews_no_update BEFORE UPDATE ON ai_reviews
                    BEGIN SELECT RAISE(ABORT,'AI reviews are append-only'); END;
                CREATE TRIGGER ai_reviews_no_delete BEFORE DELETE ON ai_reviews
                    BEGIN SELECT RAISE(ABORT,'AI reviews are append-only'); END;
                DROP TABLE ai_reviews_v6;
                DROP TABLE ai_runs_v6;

                CREATE TABLE risk_threshold_versions (
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    version INTEGER NOT NULL,
                    overload_percent REAL NOT NULL CHECK(overload_percent>=1 AND overload_percent<=1000),
                    blocked_workdays REAL NOT NULL CHECK(blocked_workdays>=0 AND blocked_workdays<=365),
                    changed_by INTEGER NOT NULL REFERENCES users(id),
                    changed_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    PRIMARY KEY(project_id,version)
                );
                CREATE TRIGGER risk_thresholds_no_update BEFORE UPDATE ON risk_threshold_versions
                    BEGIN SELECT RAISE(ABORT,'Risk thresholds are append-only'); END;
                CREATE TRIGGER risk_thresholds_no_delete BEFORE DELETE ON risk_threshold_versions
                    BEGIN SELECT RAISE(ABORT,'Risk thresholds are append-only'); END;

                CREATE TABLE improvement_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id),
                    source_run_id INTEGER NOT NULL,
                    source_item_key TEXT NOT NULL,
                    source_kind TEXT NOT NULL CHECK(source_kind IN ('risk','efficiency')),
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    owner_id INTEGER NOT NULL REFERENCES users(id),
                    due_date TEXT NOT NULL,
                    next_check_date TEXT NOT NULL,
                    baseline_metric_key TEXT NOT NULL,
                    baseline_metric_value REAL NOT NULL,
                    review_metric TEXT NOT NULL,
                    current_metric_value REAL,
                    status TEXT NOT NULL DEFAULT '待处理' CHECK(status IN ('待处理','进行中','已完成')),
                    version INTEGER NOT NULL DEFAULT 1,
                    review_note TEXT NOT NULL DEFAULT '',
                    created_by INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_by INTEGER NOT NULL REFERENCES users(id),
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(project_id,source_run_id,source_item_key),
                    FOREIGN KEY(project_id,source_run_id) REFERENCES ai_runs(project_id,id)
                );
                CREATE INDEX improvement_actions_project ON improvement_actions(project_id,status,id DESC);
                PRAGMA user_version=7;
                COMMIT;
                ''')
            finally:
                db.execute('PRAGMA foreign_keys=ON')
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise RuntimeError('Database migration produced invalid foreign keys')
