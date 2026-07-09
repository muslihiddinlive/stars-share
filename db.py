import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "stars_share.db"


def init_db(path: str = DB_PATH):
    global DB_PATH
    DB_PATH = path
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER NOT NULL DEFAULT 0,
                has_paid INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id INTEGER,
                to_id INTEGER,
                amount INTEGER,
                fee INTEGER,
                created_at INTEGER
            )
            """
        )
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def upsert_user(user_id: int, username: str | None):
    with get_conn() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            conn.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
        else:
            conn.execute(
                "INSERT INTO users (user_id, username, balance, has_paid, created_at) VALUES (?,?,0,0,?)",
                (user_id, username, int(time.time())),
            )
        conn.commit()


def get_user(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def get_user_by_username(username: str):
    username = username.lstrip("@")
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
        ).fetchone()


def credit_balance(user_id: int, amount: int, mark_paid: bool = False):
    with get_conn() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        if mark_paid:
            conn.execute("UPDATE users SET has_paid = 1 WHERE user_id=?", (user_id,))
        conn.commit()


def debit_balance(user_id: int, amount: int) -> bool:
    """Returns True if debit succeeded (sufficient balance)."""
    with get_conn() as conn:
        row = conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or row["balance"] < amount:
            return False
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
        conn.commit()
        return True


def log_transaction(from_id: int, to_id: int, amount: int, fee: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (from_id, to_id, amount, fee, created_at) VALUES (?,?,?,?,?)",
            (from_id, to_id, amount, fee, int(time.time())),
        )
        conn.commit()


def all_transactions(limit: int = 50):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def stats():
    with get_conn() as conn:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        paid_users = conn.execute("SELECT COUNT(*) c FROM users WHERE has_paid=1").fetchone()["c"]
        total_volume = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM transactions").fetchone()["s"]
        total_fees = conn.execute("SELECT COALESCE(SUM(fee),0) s FROM transactions").fetchone()["s"]
        return {
            "users": users,
            "paid_users": paid_users,
            "total_volume": total_volume,
            "total_fees": total_fees,
        }
