import sqlite3
import json
from typing import List, Dict, Any, Tuple
from cogs.misc.logger import get_home, get_logger
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

HOME_PATH = get_home()
LOGGING = get_logger()
DATABASE_PATH = HOME_PATH / "cogs" / "db" / "roles.db"


class RolesDatabase:
    def __init__(self, database_path: str = str(DATABASE_PATH)):
        self.database_path = database_path
        self.create_tables()
        # Insert default roles
        self.default_users = [
            {"nickname": "owner", "roles" : ["superadmin"]}
        ]
        self.default_roles = [
            {"name": "superadmin", "permissions": ["monitor", "control", "configure"], "inherits": ["admin"]},
            {"name": "admin", "permissions": ["monitor", "control"], "inherits": ["user"]},
            {"name": "user", "permissions": ["monitor"], "inherits": []},
        ]
        self.default_permissions = [
            {"name": "monitor"},
            {"name": "control"},
            {"name": "configure"}
        ]
    
    def get_default_users(self):
        return self.default_users

    def get_default_roles(self):
        return self.default_roles

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def health_check_decorator(func):
        def wrapper(*args, **kwargs):
            # Assuming the first argument is always the instance of the class
            instance = args[0]
            instance.health_check()
            return func(*args, **kwargs)
        return wrapper
    
    def health_check(self) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            # Remove orphaned records from the user_roles table
            cursor.execute("""
                DELETE FROM user_roles
                WHERE user_id NOT IN (SELECT id FROM users)
                OR role_id NOT IN (SELECT id FROM roles)
            """)

            # Remove orphaned records from the role_permissions table
            cursor.execute("""
                DELETE FROM role_permissions
                WHERE role_id NOT IN (SELECT id FROM roles)
                OR permission_id NOT IN (SELECT id FROM permissions)
            """)

            conn.commit()


    def create_tables(self, discord_id = None):
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                inherits TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id INTEGER,
                permission_id INTEGER,
                FOREIGN KEY (role_id) REFERENCES roles (id),
                FOREIGN KEY (permission_id) REFERENCES permissions (id),
                UNIQUE (role_id, permission_id)
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                discord_id TEXT UNIQUE,
                nickname TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER,
                role_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (role_id) REFERENCES roles (id),
                UNIQUE (user_id, role_id)
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                threshold INTEGER NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 0,
                notified BOOLEAN NOT NULL DEFAULT 0
            )
            """)
            conn.commit()
    
    def add_default_data(self, discord_id=None):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            
            # Insert default permissions if the permissions table is empty
            cursor.execute("SELECT COUNT(*) FROM permissions")
            if cursor.fetchone()[0] == 0:
                for permission in self.default_permissions:
                    cursor.execute(
                        "INSERT INTO permissions (name) VALUES (?)", (permission["name"],))

                conn.commit()

            # Check if the roles table is empty
            cursor.execute("SELECT COUNT(*) FROM roles")
            if cursor.fetchone()[0] == 0:
                if discord_id is None:  # Quit here, so we can recall function with the discord ID.
                    return False

                for role in self.default_roles:
                    cursor.execute("INSERT INTO roles (name, inherits) VALUES (?, ?)",
                                (role["name"], json.dumps(role["inherits"])))
                    role_id = cursor.lastrowid

                    for permission_name in role["permissions"]:
                        cursor.execute("SELECT id FROM permissions WHERE name = ?", (permission_name,))
                        permission_id = cursor.fetchone()[0]
                        cursor.execute("INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?)", (role_id, permission_id))

                conn.commit()

            # Check if the users table is empty
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                if discord_id is None:  # Quit here, so we can recall function with the discord ID.
                    return False

                for default_user in self.default_users:
                    cursor.execute("INSERT INTO users (discord_id, nickname) VALUES (?, ?)",
                                (discord_id, default_user["nickname"]))
                    user_id = cursor.lastrowid

                    for role_name in default_user["roles"]:
                        cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
                        role_id = cursor.fetchone()[0]
                        cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))

                conn.commit()
        return True

    def add_default_alerts_data(self):
        initial_alerts = [(1, 'Warning', 'Disk Utilisation', 80, 0),
                  (2, 'Warning','Disk Utilisation', 90, 0),
                  (3, 'Critical', 'Disk Utilisation', 95, 0),
                  (4, 'Fatal', 'Disk Utilisation', 100, 0)]

        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
            INSERT INTO alerts (id, severity, type, threshold, active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """, initial_alerts)
            conn.commit()

    @health_check_decorator
    def update_disk_utilization_alerts(self, percent_used):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            # Retrieve all disk utilization alerts in descending order of severity
            cursor.execute("SELECT id, severity, threshold, active, notified FROM alerts WHERE type = 'Disk Utilisation' ORDER BY severity DESC")
            alerts = cursor.fetchall()

            # Initialize variables to track the most severe alert that meets the criteria
            most_severe_applicable_alert = None

            # Iterate through all alerts to find the most severe one that meets the disk utilization threshold
            for alert in alerts:
                alert_id, severity, threshold, active, notified = alert
                if percent_used >= threshold:
                    most_severe_applicable_alert = alert
                    # Don't break here as we want the most severe one

            alert_activated = {}  # Dict to track if any alert was activated

            # Update the alerts based on the identified most severe applicable alert
            for alert in alerts:
                alert_id, severity, threshold, active, notified = alert

                if most_severe_applicable_alert is not None and alert_id == most_severe_applicable_alert[0]:
                    # Activate the most severe applicable alert if it's not already active
                    if not active or not notified:
                        cursor.execute("UPDATE alerts SET active = 1, notified = 0 WHERE id = ?", (alert_id,))
                        alert_activated = {'id': alert_id, 'severity': severity, 'threshold': threshold}
                else:
                    # Deactivate all other alerts
                    if active or notified:
                        cursor.execute("UPDATE alerts SET active = 0, notified = 0 WHERE id = ?", (alert_id,))

            conn.commit()
            return alert_activated  # Return the most severe activated alert's info or None if no alerts were activated

    @health_check_decorator
    def get_latest_active_alert(self, alert_type=None, alert_id=None):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            # Query to select the most severe active alert for the given type
            if alert_type:
                cursor.execute("""
                SELECT severity, threshold, active, notified
                FROM alerts
                WHERE type = ? AND active = 1 
                ORDER BY id DESC 
                LIMIT 1
                """, (alert_type,))
            elif alert_id:
                cursor.execute("""
                SELECT severity, threshold, active, notified
                FROM alerts
                WHERE id = ? AND active = 1 
                ORDER BY id DESC 
                LIMIT 1
                """, (alert_id,))
            # Fetch the result
            result = cursor.fetchone()
            return dict(result)

    @health_check_decorator
    def update_alert_with_notified(self, alert_id):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            # Update all active alerts of the given type to have notified = 1
            cursor.execute("""
            UPDATE alerts
            SET notified = 1
            WHERE id = ?
            """, (alert_id,))
            conn.commit()

    # Other methods are updated to use the "self.get_conn()" context manager
    @health_check_decorator
    def update_roles_and_users(self, roles: List[Dict[str, Any]], users: List[Dict[str, Any]]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_roles")
            cursor.execute("DELETE FROM roles")
            cursor.execute("DELETE FROM users")

            for role in roles:
                cursor.execute("INSERT INTO roles (name) VALUES (?)", (role["name"],))

            for user in users:
                cursor.execute("INSERT INTO users (discord_id, nickname) VALUES (?, ?)", (user["discord_id"], user["nickname"]))
                user_id = cursor.lastrowid
                for role_name in user["roles"]:
                    cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
                    role_id = cursor.fetchone()["id"]
                    cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))

            conn.commit()


    def get_all_users(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM users")
            users = [dict(row) for row in cursor.fetchall()]

        return users
    
    @health_check_decorator
    def get_all_users_with_roles(self):
        with self.get_conn() as conn:
            cursor = conn.cursor()

            # retrieve all users and their associated roles
            cursor.execute("""
                SELECT users.id, users.discord_id, users.nickname, GROUP_CONCAT(roles.name, ', ') AS roles
                FROM users
                LEFT JOIN user_roles ON users.id = user_roles.user_id
                LEFT JOIN roles ON user_roles.role_id = roles.id
                GROUP BY users.id;
            """)

            # format the results as a list of dictionaries
            results = []
            for row in cursor.fetchall():
                user = {
                    'id': row[0],
                    'discord_id': row[1],
                    'nickname': row[2],
                    'roles': row[3].split(', ') if row[3] else []
                }
                results.append(user)

            return results
    
    @health_check_decorator
    def get_all_permissions(self):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM permissions")
            permissions = [dict(row) for row in cursor.fetchall()]

        return permissions
    
    @health_check_decorator
    def get_all_roles_with_permissions(self):
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT roles.id, roles.name, GROUP_CONCAT(permissions.name, ', ') AS permissions
                FROM roles
                LEFT JOIN role_permissions ON roles.id = role_permissions.role_id
                LEFT JOIN permissions ON role_permissions.permission_id = permissions.id
                GROUP BY roles.id;
            """)

            results = []
            for row in cursor.fetchall():
                role = {
                    'id': row[0],
                    'name': row[1],
                    'permissions': row[2].split(', ') if row[2] else []
                }
                results.append(role)

            return results

    @health_check_decorator
    def get_all_roles(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM roles")
            roles = [dict(row) for row in cursor.fetchall()]

        return roles

    @health_check_decorator
    def get_role_by_name(self, role_name: str) -> Dict[str, Any]:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM roles WHERE name = ?", (role_name,))
            row = cursor.fetchone()

        if row:
            return dict(row)
        else:
            return {}

    @health_check_decorator
    def get_user_by_discord_id(self, discord_id: str) -> Dict[str, Any]:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
            row = cursor.fetchone()

        if row:
            return dict(row)
        else:
            return {}
    
    @health_check_decorator
    def get_discord_owner_id(self) -> str:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT discord_id FROM users WHERE nickname = 'owner'")
            row = cursor.fetchone()

        if row:
            return row[0]
        else:
            return ""
    
    @health_check_decorator
    def update_discord_owner_id(self, discord_id: int) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET discord_id = ? WHERE nickname = 'owner'", (discord_id,))
            conn.commit()

    @health_check_decorator  
    def get_user_roles_by_discord_id(self, discord_id: str) -> List[str]:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT roles.name
                FROM roles
                JOIN user_roles ON roles.id = user_roles.role_id
                JOIN users ON users.id = user_roles.user_id
                WHERE users.discord_id = ?
            """, (discord_id,))

            roles = [row["name"] for row in cursor.fetchall()]

        return roles
    
    @health_check_decorator
    def get_user_permissions_by_discord_id(self, discord_id: str) -> List[str]:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT permissions.name
                FROM permissions
                JOIN role_permissions ON permissions.id = role_permissions.permission_id
                JOIN roles ON roles.id = role_permissions.role_id
                JOIN user_roles ON roles.id = user_roles.role_id
                JOIN users ON users.id = user_roles.user_id
                WHERE users.discord_id = ?
            """, (discord_id,))

            permissions = [row["name"] for row in cursor.fetchall()]

        return permissions

    @health_check_decorator
    def get_user_nickname_by_discord_id(self, discord_id: str) -> str:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT nickname FROM users WHERE discord_id = ?", (discord_id,))
            row = cursor.fetchone()

        if row:
            return row["nickname"]
        else:
            return ""

    @health_check_decorator
    def add_new_user(self, user: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO users (discord_id, nickname)
                VALUES (?, ?)
            """, (user["discord_id"], user["nickname"]))

            cursor.execute("SELECT id FROM users WHERE discord_id = ?", (user["discord_id"],))
            user_id = cursor.fetchone()["id"]

            for role_name in user["roles"]:
                self.insert_or_update_role(cursor, user_id, role_name)

            conn.commit()

    def insert_or_update_role(self, cursor, user_id, role_name):
        cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
        role_id = cursor.fetchone()["id"]

        cursor.execute("""
            INSERT OR REPLACE INTO user_roles (user_id, role_id)
            VALUES (?, ?)
        """, (user_id, role_id))

    @health_check_decorator
    def add_role_to_user(self, user_id: int, role_id: int) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))
            conn.commit()
    
    @health_check_decorator
    def remove_role_from_user(self, user_id: int, role_id: int) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
            conn.commit()

    @health_check_decorator
    def remove_user(self, user: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM users WHERE discord_id = ?", (user["discord_id"],))
            user_id = cursor.fetchone()[0]

            cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM users WHERE discord_id = ?", (user["discord_id"],))

            conn.commit()

    @health_check_decorator
    def edit_user(self, user: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET nickname = ? WHERE discord_id = ?", (user["nickname"], user["discord_id"]))

            cursor.execute("SELECT id FROM users WHERE discord_id = ?", (user["discord_id"],))
            user_id = cursor.fetchone()["id"]
            cursor.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))

            for role_name in user["roles"]:
                cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
                role_id = cursor.fetchone()["id"]
                cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))

            conn.commit()


    @health_check_decorator
    def add_new_role(self, role: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO roles (name)
                VALUES (?)
            """, (role["name"],))

            cursor.execute("SELECT id FROM roles WHERE name = ?", (role["name"],))
            role_id = cursor.fetchone()[0]

            cursor.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))

            for permission_name in role["permissions"]:
                self.insert_or_update_permission(cursor, role_id, permission_name)

            conn.commit()

    def insert_or_update_permission(self, cursor, role_id, permission_name):
        cursor.execute("SELECT id FROM permissions WHERE name = ?", (permission_name,))
        permission_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT OR REPLACE INTO role_permissions (role_id, permission_id)
            VALUES (?, ?)
        """, (role_id, permission_id))


    @health_check_decorator
    def remove_role(self, role: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM roles WHERE name = ?", (role["name"],))
            role_id = cursor.fetchone()[0]

            cursor.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
            cursor.execute("DELETE FROM user_roles WHERE role_id = ?", (role_id,))
            cursor.execute("DELETE FROM roles WHERE name = ?", (role["name"],))

            conn.commit()

    @health_check_decorator
    def edit_role(self, role: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE roles SET permissions = ? WHERE name = ?",
                           (json.dumps(role["permissions"]), role["name"]))
            conn.commit()

    def close(self):
        pass  # No longer needed since connections are closed after each use
