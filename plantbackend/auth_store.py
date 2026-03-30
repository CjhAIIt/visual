"""SQLite-backed auth and ownership storage."""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_ADMIN_USERNAME = str(os.getenv("BOOTSTRAP_ADMIN_USERNAME", "root") or "root").strip() or "root"
DEFAULT_ADMIN_PASSWORD = str(os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "") or "").strip()
DEFAULT_USER_USERNAME = str(os.getenv("BOOTSTRAP_USER_USERNAME", "root_user") or "root_user").strip() or "root_user"
DEFAULT_USER_PASSWORD = str(os.getenv("BOOTSTRAP_USER_PASSWORD", "") or "").strip()
ALLOW_INSECURE_DEFAULT_USERS = str(os.getenv("ALLOW_INSECURE_DEFAULT_USERS", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PASSWORD_ITERATIONS = 120_000
SESSION_TOKEN_PREFIX = "sha256"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_timestamp() -> str:
    return _utc_now().isoformat(timespec="seconds")


def normalize_username(username: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9_-]+", "_", str(username or "").strip())
    normalized = re.sub(r"_+", "_", raw).strip("._")
    if len(normalized) < 3:
        raise RuntimeError("用户名至少需要 3 个字符，只能包含字母、数字、下划线或中划线。")
    return normalized[:48]


def normalize_display_name(display_name: Optional[str], fallback_username: str) -> str:
    raw = re.sub(r"\s+", " ", str(display_name or "").strip()).strip()
    return raw[:48] if raw else fallback_username


class AuthStore:
    def __init__(self, db_path: str, session_hours: int = 168) -> None:
        self.db_path = Path(db_path)
        self.session_hours = max(1, int(session_hours))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._seed_default_users()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    is_disabled INTEGER NOT NULL DEFAULT 0,
                    is_flagged INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS dataset_ownership (
                    dataset_name TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    is_public INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS model_ownership (
                    model_name TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    is_public INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS class_advice_cache (
                    dataset_name TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    advice_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    detail TEXT,
                    generated_by_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (dataset_name, class_name),
                    FOREIGN KEY(generated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_class_advice_cache_class_name
                ON class_advice_cache(class_name);
                """
            )
            self._ensure_column(conn, "users", "is_disabled", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "users", "is_flagged", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "dataset_ownership", "is_public", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "model_ownership", "is_public", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "class_advice_cache", "detail", "TEXT")
            self._ensure_column(conn, "class_advice_cache", "generated_by_user_id", "INTEGER")
            self._ensure_column(conn, "class_advice_cache", "created_at", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "class_advice_cache", "updated_at", "TEXT NOT NULL DEFAULT ''")

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _seed_default_users(self) -> None:
        primary_admin = self.get_primary_admin_user()
        if primary_admin:
            return

        # A first-run password must be explicit unless the operator opts into
        # insecure demo defaults. This is safer for deployment and competition
        # demos where the app may briefly face a shared network.
        admin_password = DEFAULT_ADMIN_PASSWORD
        user_password = DEFAULT_USER_PASSWORD
        if ALLOW_INSECURE_DEFAULT_USERS:
            admin_password = admin_password or "root"
            user_password = user_password or "root"

        if not admin_password:
            raise RuntimeError(
                "首次启动未检测到管理员账号，请先设置 BOOTSTRAP_ADMIN_PASSWORD 环境变量后再启动后端。"
            )

        self.create_user(
            DEFAULT_ADMIN_USERNAME,
            admin_password,
            role="admin",
            display_name=DEFAULT_ADMIN_USERNAME,
            allow_existing=True,
        )
        if user_password:
            self.create_user(
                DEFAULT_USER_USERNAME,
                user_password,
                role="user",
                display_name=DEFAULT_USER_USERNAME,
                allow_existing=True,
            )

    def _hash_password(self, password: str, salt_hex: Optional[str] = None) -> str:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt,
            PASSWORD_ITERATIONS,
        )
        return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"

    def _verify_password(self, password: str, password_hash: str) -> bool:
        try:
            iterations_text, salt_hex, digest_hex = str(password_hash or "").split("$", 2)
            iterations = int(iterations_text)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
        except (TypeError, ValueError):
            return False

        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            str(password or "").encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(candidate, expected)

    def _hash_session_token(self, token: str) -> str:
        safe_token = str(token or "").strip()
        if not safe_token:
            return ""
        digest = hashlib.sha256(safe_token.encode("utf-8")).hexdigest()
        return f"{SESSION_TOKEN_PREFIX}${digest}"

    def _row_to_user(self, row: sqlite3.Row) -> Dict[str, object]:
        return {
            "id": int(row["id"]),
            "username": str(row["username"]),
            "display_name": str(row["display_name"]),
            "role": str(row["role"]),
            "is_disabled": bool(row["is_disabled"]) if "is_disabled" in row.keys() else False,
            "is_flagged": bool(row["is_flagged"]) if "is_flagged" in row.keys() else False,
            "created_at": str(row["created_at"]),
        }

    def get_user_by_username(self, username: str) -> Optional[Dict[str, object]]:
        safe_username = normalize_username(username)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, display_name, role, is_disabled, is_flagged, created_at FROM users WHERE username = ?",
                (safe_username,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, display_name, role, is_disabled, is_flagged, created_at FROM users WHERE id = ?",
                (int(user_id),),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_primary_admin_user(self) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, role, is_disabled, is_flagged, created_at
                FROM users
                WHERE role = 'admin'
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()
        return self._row_to_user(row) if row else None

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        display_name: Optional[str] = None,
        allow_existing: bool = False,
    ) -> Dict[str, object]:
        safe_username = normalize_username(username)
        if len(str(password or "")) < 4:
            raise RuntimeError("密码至少需要 4 个字符。")
        safe_role = "admin" if role == "admin" else "user"
        safe_display_name = normalize_display_name(display_name, safe_username)

        existing = self.get_user_by_username(safe_username)
        if existing:
            if allow_existing:
                return existing
            raise RuntimeError(f"用户名已存在：{safe_username}")

        password_hash = self._hash_password(password)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash, role, is_disabled, is_flagged, created_at)
                VALUES (?, ?, ?, ?, 0, 0, ?)
                """,
                (safe_username, safe_display_name, password_hash, safe_role, _utc_timestamp()),
            )
            user_id = int(cursor.lastrowid)
        created = self.get_user_by_id(user_id)
        if not created:
            raise RuntimeError("用户创建失败。")
        return created

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, object]]:
        safe_username = normalize_username(username)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, password_hash, role, is_disabled, is_flagged, created_at
                FROM users
                WHERE username = ?
                """,
                (safe_username,),
            ).fetchone()

        if not row or not self._verify_password(password, str(row["password_hash"])):
            return None
        if bool(row["is_disabled"]):
            raise RuntimeError("该账号已被管理员封禁，请联系管理员。")
        return self._row_to_user(row)

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_session_token(token)
        created_at = _utc_now()
        expires_at = created_at + timedelta(hours=self.session_hours)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, int(user_id), created_at.isoformat(timespec="seconds"), expires_at.isoformat(timespec="seconds")),
            )
        return token

    def delete_session(self, token: str) -> None:
        safe_token = str(token or "").strip()
        token_hash = self._hash_session_token(safe_token)
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (safe_token, token_hash))

    def delete_sessions_for_user(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))

    def get_user_by_token(self, token: str) -> Optional[Dict[str, object]]:
        safe_token = str(token or "").strip()
        if not safe_token:
            return None
        token_hash = self._hash_session_token(safe_token)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    users.id,
                    users.username,
                    users.display_name,
                    users.role,
                    users.is_disabled,
                    users.is_flagged,
                    users.created_at,
                    sessions.token AS session_token,
                    sessions.expires_at
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token IN (?, ?)
                """,
                (safe_token, token_hash),
            ).fetchone()

            if not row:
                return None

            try:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
            except ValueError:
                conn.execute("DELETE FROM sessions WHERE token = ?", (str(row["session_token"]),))
                return None

            if expires_at <= _utc_now():
                conn.execute("DELETE FROM sessions WHERE token = ?", (str(row["session_token"]),))
                return None

            if bool(row["is_disabled"]):
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(row["id"]),))
                return None

            if str(row["session_token"]) == safe_token:
                conn.execute("UPDATE sessions SET token = ? WHERE token = ?", (token_hash, safe_token))

        return self._row_to_user(row)

    def ensure_dataset_owner(self, dataset_name: str, owner_user_id: int) -> None:
        self.ensure_dataset_access_entry(dataset_name, owner_user_id, is_public=False, overwrite_existing=False)

    def ensure_dataset_access_entry(
        self,
        dataset_name: str,
        owner_user_id: int,
        is_public: bool = False,
        overwrite_existing: bool = False,
    ) -> None:
        with self._connect() as conn:
            if overwrite_existing:
                conn.execute(
                    """
                    INSERT INTO dataset_ownership (dataset_name, owner_user_id, is_public, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(dataset_name) DO UPDATE SET
                        owner_user_id = excluded.owner_user_id,
                        is_public = excluded.is_public
                    """,
                    (str(dataset_name), int(owner_user_id), 1 if is_public else 0, _utc_timestamp()),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dataset_ownership (dataset_name, owner_user_id, is_public, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(dataset_name), int(owner_user_id), 1 if is_public else 0, _utc_timestamp()),
                )

    def get_dataset_owner(self, dataset_name: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    dataset_ownership.dataset_name,
                    dataset_ownership.owner_user_id,
                    dataset_ownership.is_public,
                    dataset_ownership.created_at,
                    users.username AS owner_username,
                    users.display_name AS owner_display_name,
                    users.role AS owner_role
                FROM dataset_ownership
                JOIN users ON users.id = dataset_ownership.owner_user_id
                WHERE dataset_ownership.dataset_name = ?
                """,
                (str(dataset_name),),
            ).fetchone()
        if not row:
            return None
        return {
            "dataset_name": str(row["dataset_name"]),
            "owner_user_id": int(row["owner_user_id"]),
            "is_public": bool(row["is_public"]),
            "created_at": str(row["created_at"]),
            "owner_username": str(row["owner_username"]),
            "owner_display_name": str(row["owner_display_name"]),
            "owner_role": str(row["owner_role"]),
        }

    def list_dataset_names_for_user(self, user_id: int) -> List[str]:
        return [item["dataset_name"] for item in self.list_accessible_datasets_for_user(user_id)]

    def list_accessible_datasets_for_user(self, user_id: int) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    dataset_ownership.dataset_name,
                    dataset_ownership.owner_user_id,
                    dataset_ownership.is_public,
                    dataset_ownership.created_at,
                    users.username AS owner_username,
                    users.display_name AS owner_display_name,
                    users.role AS owner_role
                FROM dataset_ownership
                JOIN users ON users.id = dataset_ownership.owner_user_id
                WHERE dataset_ownership.owner_user_id = ? OR dataset_ownership.is_public = 1
                ORDER BY dataset_ownership.dataset_name
                """,
                (int(user_id),),
            ).fetchall()
        return [
            {
                "dataset_name": str(row["dataset_name"]),
                "owner_user_id": int(row["owner_user_id"]),
                "is_public": bool(row["is_public"]),
                "created_at": str(row["created_at"]),
                "owner_username": str(row["owner_username"]),
                "owner_display_name": str(row["owner_display_name"]),
                "owner_role": str(row["owner_role"]),
            }
            for row in rows
        ]

    def list_all_datasets(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    dataset_ownership.dataset_name,
                    dataset_ownership.owner_user_id,
                    dataset_ownership.is_public,
                    dataset_ownership.created_at,
                    users.username AS owner_username,
                    users.display_name AS owner_display_name,
                    users.role AS owner_role
                FROM dataset_ownership
                JOIN users ON users.id = dataset_ownership.owner_user_id
                ORDER BY dataset_ownership.dataset_name
                """
            ).fetchall()
        return [
            {
                "dataset_name": str(row["dataset_name"]),
                "owner_user_id": int(row["owner_user_id"]),
                "is_public": bool(row["is_public"]),
                "created_at": str(row["created_at"]),
                "owner_username": str(row["owner_username"]),
                "owner_display_name": str(row["owner_display_name"]),
                "owner_role": str(row["owner_role"]),
            }
            for row in rows
        ]

    def delete_dataset_owner(self, dataset_name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM dataset_ownership WHERE dataset_name = ?", (str(dataset_name),))
            conn.execute("DELETE FROM class_advice_cache WHERE dataset_name = ?", (str(dataset_name),))

    def upsert_class_advice(
        self,
        dataset_name: str,
        class_name: str,
        summary: str,
        advice: List[str],
        source: str,
        detail: Optional[str] = None,
        generated_by_user_id: Optional[int] = None,
    ) -> None:
        safe_dataset = str(dataset_name or "").strip()
        safe_class = str(class_name or "").strip()
        if not safe_dataset or not safe_class:
            raise RuntimeError("类别建议写入失败：dataset_name 或 class_name 为空。")

        safe_summary = str(summary or "").strip()
        safe_source = str(source or "builtin").strip() or "builtin"
        safe_detail = str(detail or "").strip() or None
        safe_advice = [str(item).strip() for item in advice if str(item).strip()]
        if not safe_summary or not safe_advice:
            raise RuntimeError("类别建议写入失败：summary 或 advice 为空。")

        timestamp = _utc_timestamp()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO class_advice_cache (
                    dataset_name,
                    class_name,
                    summary,
                    advice_json,
                    source,
                    detail,
                    generated_by_user_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_name, class_name) DO UPDATE SET
                    summary = excluded.summary,
                    advice_json = excluded.advice_json,
                    source = excluded.source,
                    detail = excluded.detail,
                    generated_by_user_id = excluded.generated_by_user_id,
                    updated_at = excluded.updated_at
                """,
                (
                    safe_dataset,
                    safe_class,
                    safe_summary,
                    json.dumps(safe_advice, ensure_ascii=False),
                    safe_source,
                    safe_detail,
                    int(generated_by_user_id) if generated_by_user_id is not None else None,
                    timestamp,
                    timestamp,
                ),
            )

    def _row_to_class_advice(self, row: sqlite3.Row) -> Dict[str, object]:
        try:
            advice_items = json.loads(str(row["advice_json"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            advice_items = []

        cleaned_advice = [str(item).strip() for item in advice_items if str(item).strip()]
        return {
            "dataset_name": str(row["dataset_name"]),
            "class_name": str(row["class_name"]),
            "summary": str(row["summary"]),
            "advice": cleaned_advice,
            "source": str(row["source"] or "builtin"),
            "detail": str(row["detail"] or "").strip() or None,
            "generated_by_user_id": int(row["generated_by_user_id"]) if row["generated_by_user_id"] is not None else None,
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }

    def get_class_advice(self, dataset_name: str, class_name: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    dataset_name,
                    class_name,
                    summary,
                    advice_json,
                    source,
                    detail,
                    generated_by_user_id,
                    created_at,
                    updated_at
                FROM class_advice_cache
                WHERE dataset_name = ? AND class_name = ?
                """,
                (str(dataset_name), str(class_name)),
            ).fetchone()
        return self._row_to_class_advice(row) if row else None

    def get_latest_class_advice(self, class_name: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    dataset_name,
                    class_name,
                    summary,
                    advice_json,
                    source,
                    detail,
                    generated_by_user_id,
                    created_at,
                    updated_at
                FROM class_advice_cache
                WHERE class_name = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (str(class_name),),
            ).fetchone()
        return self._row_to_class_advice(row) if row else None

    def list_class_advices_for_dataset(self, dataset_name: str) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    dataset_name,
                    class_name,
                    summary,
                    advice_json,
                    source,
                    detail,
                    generated_by_user_id,
                    created_at,
                    updated_at
                FROM class_advice_cache
                WHERE dataset_name = ?
                ORDER BY class_name
                """,
                (str(dataset_name),),
            ).fetchall()
        return [self._row_to_class_advice(row) for row in rows]

    def delete_class_advice(self, dataset_name: str, class_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM class_advice_cache WHERE dataset_name = ? AND class_name = ?",
                (str(dataset_name), str(class_name)),
            )

    def list_datasets_owned_by_user(self, user_id: int) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    dataset_name,
                    owner_user_id,
                    is_public,
                    created_at
                FROM dataset_ownership
                WHERE owner_user_id = ?
                ORDER BY dataset_name
                """,
                (int(user_id),),
            ).fetchall()
        return [
            {
                "dataset_name": str(row["dataset_name"]),
                "owner_user_id": int(row["owner_user_id"]),
                "is_public": bool(row["is_public"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def count_datasets_for_user(self, user: Dict[str, object]) -> int:
        if str(user.get("role") or "") == "admin":
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS count FROM dataset_ownership").fetchone()
        else:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM dataset_ownership
                    WHERE owner_user_id = ? OR is_public = 1
                    """,
                    (int(user["id"]),),
                ).fetchone()
        return int(row["count"]) if row else 0

    def count_models_for_user(self, user: Dict[str, object]) -> int:
        if str(user.get("role") or "") == "admin":
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS count FROM model_ownership").fetchone()
        else:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM model_ownership
                    WHERE owner_user_id = ? OR is_public = 1
                    """,
                    (int(user["id"]),),
                ).fetchone()
        return int(row["count"]) if row else 0

    def ensure_model_owner(
        self,
        model_name: str,
        owner_user_id: int,
        is_public: bool = False,
        overwrite_existing: bool = False,
    ) -> None:
        with self._connect() as conn:
            if overwrite_existing:
                conn.execute(
                    """
                    INSERT INTO model_ownership (model_name, owner_user_id, is_public, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(model_name) DO UPDATE SET
                        owner_user_id = excluded.owner_user_id,
                        is_public = excluded.is_public
                    """,
                    (str(model_name), int(owner_user_id), 1 if is_public else 0, _utc_timestamp()),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO model_ownership (model_name, owner_user_id, is_public, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(model_name), int(owner_user_id), 1 if is_public else 0, _utc_timestamp()),
                )

    def get_model_owner(self, model_name: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    model_ownership.model_name,
                    model_ownership.owner_user_id,
                    model_ownership.is_public,
                    model_ownership.created_at,
                    users.username AS owner_username,
                    users.display_name AS owner_display_name,
                    users.role AS owner_role
                FROM model_ownership
                JOIN users ON users.id = model_ownership.owner_user_id
                WHERE model_ownership.model_name = ?
                """,
                (str(model_name),),
            ).fetchone()
        if not row:
            return None
        return {
            "model_name": str(row["model_name"]),
            "owner_user_id": int(row["owner_user_id"]),
            "is_public": bool(row["is_public"]),
            "created_at": str(row["created_at"]),
            "owner_username": str(row["owner_username"]),
            "owner_display_name": str(row["owner_display_name"]),
            "owner_role": str(row["owner_role"]),
        }

    def list_accessible_models_for_user(self, user_id: int) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    model_ownership.model_name,
                    model_ownership.owner_user_id,
                    model_ownership.is_public,
                    model_ownership.created_at,
                    users.username AS owner_username,
                    users.display_name AS owner_display_name,
                    users.role AS owner_role
                FROM model_ownership
                JOIN users ON users.id = model_ownership.owner_user_id
                WHERE model_ownership.owner_user_id = ? OR model_ownership.is_public = 1
                ORDER BY model_ownership.model_name
                """,
                (int(user_id),),
            ).fetchall()
        return [
            {
                "model_name": str(row["model_name"]),
                "owner_user_id": int(row["owner_user_id"]),
                "is_public": bool(row["is_public"]),
                "created_at": str(row["created_at"]),
                "owner_username": str(row["owner_username"]),
                "owner_display_name": str(row["owner_display_name"]),
                "owner_role": str(row["owner_role"]),
            }
            for row in rows
        ]

    def list_accessible_model_names_for_user(self, user_id: int) -> List[str]:
        return [item["model_name"] for item in self.list_accessible_models_for_user(user_id)]

    def list_all_models(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    model_ownership.model_name,
                    model_ownership.owner_user_id,
                    model_ownership.is_public,
                    model_ownership.created_at,
                    users.username AS owner_username,
                    users.display_name AS owner_display_name,
                    users.role AS owner_role
                FROM model_ownership
                JOIN users ON users.id = model_ownership.owner_user_id
                ORDER BY model_ownership.model_name
                """
            ).fetchall()
        return [
            {
                "model_name": str(row["model_name"]),
                "owner_user_id": int(row["owner_user_id"]),
                "is_public": bool(row["is_public"]),
                "created_at": str(row["created_at"]),
                "owner_username": str(row["owner_username"]),
                "owner_display_name": str(row["owner_display_name"]),
                "owner_role": str(row["owner_role"]),
            }
            for row in rows
        ]

    def list_models_owned_by_user(self, user_id: int) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    model_ownership.model_name,
                    model_ownership.owner_user_id,
                    model_ownership.is_public,
                    model_ownership.created_at
                FROM model_ownership
                WHERE model_ownership.owner_user_id = ?
                ORDER BY model_ownership.model_name
                """,
                (int(user_id),),
            ).fetchall()
        return [
            {
                "model_name": str(row["model_name"]),
                "owner_user_id": int(row["owner_user_id"]),
                "is_public": bool(row["is_public"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def delete_model_owner(self, model_name: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM model_ownership WHERE model_name = ?", (str(model_name),))

    def set_user_disabled(self, user_id: int, is_disabled: bool) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET is_disabled = ? WHERE id = ?",
                (1 if is_disabled else 0, int(user_id)),
            )
        if is_disabled:
            self.delete_sessions_for_user(user_id)
        return self.get_user_by_id(user_id)

    def set_user_flagged(self, user_id: int, is_flagged: bool) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET is_flagged = ? WHERE id = ?",
                (1 if is_flagged else 0, int(user_id)),
            )
        return self.get_user_by_id(user_id)

    def delete_user(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (int(user_id),))

    def list_users(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    users.id,
                    users.username,
                    users.display_name,
                    users.role,
                    users.is_disabled,
                    users.is_flagged,
                    users.created_at,
                    COUNT(DISTINCT dataset_ownership.dataset_name) AS dataset_count,
                    COUNT(DISTINCT model_ownership.model_name) AS model_count
                FROM users
                LEFT JOIN dataset_ownership ON dataset_ownership.owner_user_id = users.id
                LEFT JOIN model_ownership ON model_ownership.owner_user_id = users.id
                GROUP BY users.id
                ORDER BY CASE WHEN users.role = 'admin' THEN 0 ELSE 1 END, users.username
                """
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "username": str(row["username"]),
                "display_name": str(row["display_name"]),
                "role": str(row["role"]),
                "is_disabled": bool(row["is_disabled"]),
                "is_flagged": bool(row["is_flagged"]),
                "created_at": str(row["created_at"]),
                "dataset_count": int(row["dataset_count"] or 0),
                "model_count": int(row["model_count"] or 0),
            }
            for row in rows
        ]
