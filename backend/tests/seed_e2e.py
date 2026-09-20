"""Test-only fixture; receives random credentials over stdin, never prints them."""
import json
import os
import sys
from app.db import migrate, connect
from app.security import hash_password

if not os.environ.get('AIMANAGER_DB'):
    raise RuntimeError('Test fixture requires an explicit AIMANAGER_DB path')
data = json.load(sys.stdin)
migrate()
with connect() as db:
    hashed = hash_password(data['password'])
    for username, name in [('qa_admin', '测试管理员'), ('qa_member', '测试成员'), ('qa_observer', '测试观察者'), ('qa_new', '待加入成员')]:
        db.execute('INSERT INTO users(username,name,password_hash) VALUES(?,?,?)', (username, name, hashed))
    db.execute("INSERT INTO projects(name) VALUES('浏览器测试项目')")
    db.execute("INSERT INTO projects(name) VALUES('隔离测试项目')")
    db.executemany('INSERT INTO memberships(project_id,user_id,role,active) VALUES(?,?,?,1)', [(1, 1, 'admin'), (1, 2, 'member'), (1, 3, 'observer'), (2, 1, 'admin')])
