from __future__ import annotations

import base64
import sqlite3
import time
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )


class SessionKeyStore:
    def __init__(self, db_path: Path, secret: str) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = Fernet(self._fernet_key_from_secret(secret))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _fernet_key_from_secret(secret: str) -> bytes:
        raw = secret.encode("utf-8")
        padded = (raw * ((32 // max(1, len(raw))) + 1))[:32]
        return base64.urlsafe_b64encode(padded)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_keys (
                    session_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    encrypted_key TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    def cleanup_expired(self) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute("DELETE FROM session_keys WHERE expires_at <= ?", (now,))

    def set(self, session_id: str, provider: str, api_key: str, ttl_seconds: int) -> None:
        now = int(time.time())
        expires_at = now + max(60, ttl_seconds)
        encrypted = self._cipher.encrypt(api_key.encode("utf-8")).decode("utf-8")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_keys (session_id, provider, encrypted_key, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    provider = excluded.provider,
                    encrypted_key = excluded.encrypted_key,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (session_id, provider, encrypted, expires_at, now),
            )

    def get(self, session_id: str) -> Optional[dict]:
        self.cleanup_expired()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT provider, encrypted_key, expires_at FROM session_keys WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        provider, encrypted_key, expires_at = row
        try:
            api_key = self._cipher.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
        except Exception:
            return None
        return {"provider": provider, "api_key": api_key, "expires_at": int(expires_at)}

    def clear(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM session_keys WHERE session_id = ?", (session_id,))
