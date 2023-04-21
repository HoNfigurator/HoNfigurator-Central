import sqlite3
import json
from typing import List, Dict, Any, Tuple
from cogs.misc.logging import get_home, get_logger
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

HOME_PATH = get_home()
LOGGING = get_logger()
DATABASE_PATH = HOME_PATH / "cogs" / "db" / "roles.db"


class RolesDatabase:
    def __init__(self, database_path: str = str(DATABASE_PATH)):
        self.database_path = database_path
        self.create_tables()

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_tables(self, discord_id = None):
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE,
                permissions TEXT
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
            conn.commit()
    
    def add_default_data(self, discord_id = None):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            # Check if the roles table is empty
            cursor.execute("SELECT COUNT(*) FROM roles")
            if cursor.fetchone()[0] == 0:
                if discord_id is None:  # Quit here, so we can recall function with the discord ID.
                    return False
                # Insert default roles
                default_roles = [
                    {"name": "Admin", "permissions": {"read": True, "write": True, "delete": True}},
                    {"name": "Member", "permissions": {"read": True, "write": True, "delete": False}},
                ]

                for role in default_roles:
                    cursor.execute("INSERT INTO roles (name, permissions) VALUES (?, ?)",
                                (role["name"], json.dumps(role["permissions"])))

            # Check if the users table is empty
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                if discord_id is None:  # Quit here, so we can recall function with the discord ID.
                    return False
                # Insert a default user
                default_user = {"discord_id": "197967989964800000", "nickname": "Owner"}

                cursor.execute("INSERT INTO users (discord_id, nickname) VALUES (?, ?)",
                            (default_user["discord_id"], default_user["nickname"]))

                # Get the ID of the inserted user and the "Admin" role
                cursor.execute("SELECT id FROM users WHERE discord_id = ?", (default_user["discord_id"],))
                user_id = cursor.fetchone()[0]

                cursor.execute("SELECT id FROM roles WHERE name = ?", ("Admin",))
                admin_role_id = cursor.fetchone()[0]

                # Assign the default user to the "Admin" role using the `user_roles` table
                cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, admin_role_id))
        return True

    # Other methods are updated to use the "self.get_conn()" context manager

    def update_roles_and_users(self, roles: List[Dict[str, Any]], users: List[Dict[str, Any]]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM user_roles")
            cursor.execute("DELETE FROM roles")
            cursor.execute("DELETE FROM users")

            for role in roles:
                cursor.execute("INSERT INTO roles (name, permissions) VALUES (?, ?)", (role["name"], json.dumps(role["permissions"])))

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

    def get_all_roles(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        with self.get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM roles")
            roles = [dict(row) for row in cursor.fetchall()]

        return roles

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

    def add_new_user(self, user: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (discord_id, nickname) VALUES (?, ?)", (user["discord_id"], user["nickname"]))
            user_id = cursor.lastrowid

            for role_name in user["roles"]:
                cursor.execute("SELECT id FROM roles WHERE name = ?", (role_name,))
                role_id = cursor.fetchone()["id"]
                cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))

            conn.commit()
    
    def add_role_to_user(self, user_id: int, role_id: int) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))
            conn.commit()
    
    def remove_role_from_user(self, user_id: int, role_id: int) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id))
            conn.commit()

    def remove_user(self, discord_id: str) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM users WHERE discord_id = ?", (discord_id,))
            conn.commit()

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


    def add_new_role(self, role: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO roles (name, permissions) VALUES (?, ?)",
                           (role["name"], json.dumps(role["permissions"])))
            conn.commit()

    def remove_role(self, name: str) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM roles WHERE name = ?", (name,))
            conn.commit()

    def edit_role(self, role: Dict[str, Any]) -> None:
        with self.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE roles SET permissions = ? WHERE name = ?",
                           (json.dumps(role["permissions"]), role["name"]))
            conn.commit()

    def close(self):
        pass  # No longer needed since connections are closed after each use
