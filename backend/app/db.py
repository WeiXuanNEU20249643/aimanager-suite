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
        if version > 3:
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
