"""Local provisioning without default credentials or fabricated business records."""
import argparse
import getpass
import sqlite3
from .db import connect, migrate
from .security import hash_password


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate')
    account = sub.add_parser('create-user')
    account.add_argument('username')
    account.add_argument('--name', required=True)
    project = sub.add_parser('create-project')
    project.add_argument('name')
    project.add_argument('--admin', required=True)
    args = parser.parse_args()
    if args.command != 'migrate' and (not args.name.strip() or len(args.name.strip()) > 200):
        parser.error('Name must contain 1 to 200 characters')
    if args.command == 'create-user' and (not args.username.strip() or len(args.username.strip()) > 200):
        parser.error('Username must contain 1 to 200 characters')
    migrate()
    if args.command == 'migrate':
        with connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
        print(f'Schema version {version} ready; existing data preserved.')
        return
    try:
        with connect() as db:
            if args.command == 'create-user':
                password = getpass.getpass('Password (at least 12 characters): ')
                if len(password) < 12 or password != getpass.getpass('Confirm password: '):
                    parser.error('Password too short or confirmation does not match')
                db.execute('INSERT INTO users(username,name,password_hash) VALUES(?,?,?)', (args.username.strip(), args.name.strip(), hash_password(password)))
                print('Account created.')
            else:
                row = db.execute('SELECT id FROM users WHERE username=? AND active=1', (args.admin,)).fetchone()
                if not row:
                    parser.error('Create the administrator account first')
                pid = db.execute('INSERT INTO projects(name) VALUES(?)', (args.name,)).lastrowid
                db.execute("INSERT INTO memberships(project_id,user_id,role,active) VALUES(?,?,'admin',1)", (pid, row['id']))
                print(f'Project created: {pid}')
    except sqlite3.IntegrityError:
        parser.error('Record already exists or violates a data constraint')


if __name__ == '__main__':
    main()
