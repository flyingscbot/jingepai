"""SQLite 用户库（业界常见做法）。

- 密码：Werkzeug scrypt 单向哈希（不可逆，登录时比对哈希）
- 用户 ID：UUID4 hex，全局唯一
- 资料夹：users/<user_id>/，头像文件放资料夹，不入库
- 用户名：登录名即展示名
- 角色：默认 user
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import urllib.parse
import urllib.request
import uuid
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "users.db")
USERS_DIR = os.path.join(BASE_DIR, "users")

PASSWORD_METHOD = "scrypt"
DEFAULT_ROLE = "user"
AVATAR_CANDIDATES = (
    "avatar.webp",
    "avatar.png",
    "avatar.jpg",
    "avatar.jpeg",
    "avatar.svg",
)
ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
TRADE_DIR_NAME = "trade_file"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(users)").fetchall()
    return {r["name"] for r in rows}


def init_db() -> None:
    os.makedirs(USERS_DIR, exist_ok=True)
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if exists:
            cols = _table_columns(conn)
            if (
                "password_enc" in cols
                or "password_hash" not in cols
                or "avatar" in cols
                or "nickname" in cols
                or "profile_dir" in cols
            ):
                # 旧 schema 整表重建
                conn.execute("DROP TABLE users")
                conn.commit()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
        conn.execute("UPDATE users SET role = 'user' WHERE role IS NULL OR role != 'user'")
        conn.commit()


def _row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def generate_unique_id(conn: sqlite3.Connection) -> str:
    for _ in range(64):
        user_id = uuid.uuid4().hex
        exists = conn.execute(
            "SELECT 1 FROM users WHERE id = ? LIMIT 1", (user_id,)
        ).fetchone()
        if not exists:
            return user_id
    raise RuntimeError("无法生成唯一用户 id")


def profile_dir_for(user_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", user_id):
        raise ValueError("非法用户 id")
    return user_id


def ensure_profile_dir(user_id: str) -> str:
    folder = profile_dir_for(user_id)
    os.makedirs(os.path.join(USERS_DIR, folder), exist_ok=True)
    return folder


def trade_dir(user_id: str) -> str:
    """用户交易文件目录：users/<id>/trade_file/（不存在则创建）。"""
    path = os.path.join(USERS_DIR, profile_dir_for(user_id), TRADE_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def safe_trade_filename(name: str) -> str:
    name = os.path.basename((name or "").strip().replace("\\", "/"))
    name = name.replace("\x00", "")
    if not name or name in {".", ".."}:
        raise ValueError("文件名无效")
    if re.search(r'[<>:"|?*]', name):
        raise ValueError("文件名包含非法字符")
    return name


def _unique_trade_path(directory: str, filename: str) -> tuple[str, str]:
    base, ext = os.path.splitext(filename)
    candidate = filename
    index = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}({index}){ext}"
        index += 1
    return candidate, os.path.join(directory, candidate)


def list_trade_files(user_id: str) -> list[dict[str, Any]]:
    directory = trade_dir(user_id)
    items: list[dict[str, Any]] = []
    for name in sorted(os.listdir(directory), key=str.lower):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        items.append(
            {
                "name": name,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        )
    return items


def save_trade_file(user_id: str, file_storage) -> dict[str, Any]:
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("请选择要上传的文件")
    filename = safe_trade_filename(file_storage.filename)
    directory = trade_dir(user_id)
    save_name, path = _unique_trade_path(directory, filename)
    file_storage.save(path)
    stat = os.stat(path)
    return {
        "name": save_name,
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
    }


def delete_trade_file(user_id: str, filename: str) -> None:
    filename = safe_trade_filename(filename)
    path = os.path.join(trade_dir(user_id), filename)
    if not os.path.isfile(path):
        raise ValueError("文件不存在")
    os.remove(path)


def read_trade_file(user_id: str, filename: str) -> tuple[str, bytes]:
    """读取用户 trade_file 目录中的文件内容。"""
    filename = safe_trade_filename(filename)
    path = os.path.join(trade_dir(user_id), filename)
    if not os.path.isfile(path):
        raise ValueError("文件不存在，请先在「我的交易数据」中上传")
    with open(path, "rb") as f:
        return filename, f.read()


def find_avatar_filename(user_id: str) -> str | None:
    folder = os.path.join(USERS_DIR, profile_dir_for(user_id))
    for name in AVATAR_CANDIDATES:
        if os.path.isfile(os.path.join(folder, name)):
            return name
    return None


def avatar_url(user_id: str | None, fallback_seed: str = "guest") -> str:
    """头像地址由资料夹约定生成，不读数据库。"""
    if user_id and re.fullmatch(r"[0-9a-f]{32}", user_id):
        name = find_avatar_filename(user_id)
        if name:
            path = os.path.join(USERS_DIR, user_id, name)
            version = int(os.path.getmtime(path))
            return f"/user_assets/{user_id}/{name}?v={version}"
    seed = urllib.parse.quote(fallback_seed or "guest")
    return f"https://api.dicebear.com/7.x/avataaars/svg?seed={seed}"


def ensure_avatar_file(user_id: str, seed: str) -> None:
    if find_avatar_filename(user_id):
        return
    folder = ensure_profile_dir(user_id)
    local_path = os.path.join(USERS_DIR, folder, "avatar.svg")
    remote = f"https://api.dicebear.com/7.x/avataaars/svg?seed={urllib.parse.quote(seed)}"
    try:
        urllib.request.urlretrieve(remote, local_path)
    except Exception:
        pass


def clear_avatar_files(user_id: str) -> None:
    folder = os.path.join(USERS_DIR, profile_dir_for(user_id))
    for name in AVATAR_CANDIDATES:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            os.remove(path)


def save_avatar_upload(user_id: str, file_storage) -> str:
    """保存上传头像到资料夹，返回公开 URL。"""
    if not file_storage or not file_storage.filename:
        raise ValueError("请选择头像文件")
    filename = secure_filename(file_storage.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_AVATAR_EXT:
        raise ValueError("仅支持 png / jpg / webp / svg / gif")
    ensure_profile_dir(user_id)
    clear_avatar_files(user_id)
    save_name = f"avatar{ext}"
    path = os.path.join(USERS_DIR, user_id, save_name)
    file_storage.save(path)
    return avatar_url(user_id)


def hash_password(password: str) -> str:
    return generate_password_hash(password, method=PASSWORD_METHOD)


def verify_password(user: dict[str, Any], password: str) -> bool:
    stored = user.get("password_hash") or ""
    if not stored or not password:
        return False
    return check_password_hash(stored, password)


def get_user_by_name(username: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE LIMIT 1",
            (username.strip(),),
        ).fetchone()
        return _row_to_user(row)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? LIMIT 1", (user_id,)
        ).fetchone()
        return _row_to_user(row)


def create_user(
    username: str, password: str, role: str = DEFAULT_ROLE
) -> dict[str, Any]:
    username = username.strip()
    if not username or not password:
        raise ValueError("账号密码不能为空")
    if get_user_by_name(username):
        raise ValueError("该账号已存在")

    with get_conn() as conn:
        user_id = generate_unique_id(conn)
        ensure_profile_dir(user_id)
        ensure_avatar_file(user_id, username)
        password_hash = hash_password(password)
        conn.execute(
            """
            INSERT INTO users (id, username, password_hash, role)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                password_hash,
                role or DEFAULT_ROLE,
            ),
        )
        conn.commit()

    user = get_user_by_id(user_id)
    assert user is not None
    return user


def update_username(user_id: str, username: str) -> dict[str, Any]:
    username = (username or "").strip()
    if not username:
        raise ValueError("用户名不能为空")
    if len(username) > 32:
        raise ValueError("用户名最多 32 个字符")
    with get_conn() as conn:
        taken = conn.execute(
            """
            SELECT 1 FROM users
            WHERE username = ? COLLATE NOCASE AND id != ?
            LIMIT 1
            """,
            (username, user_id),
        ).fetchone()
        if taken:
            raise ValueError("该用户名已被占用")
        conn.execute(
            "UPDATE users SET username = ? WHERE id = ?",
            (username, user_id),
        )
        conn.commit()
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("用户不存在")
    return user


def update_password(user_id: str, old_password: str, new_password: str) -> None:
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("用户不存在")
    if not new_password or len(new_password) < 6:
        raise ValueError("新密码至少 6 位")
    if not verify_password(user, old_password):
        raise ValueError("当前密码不正确")
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        conn.commit()


def ensure_user_folder(user: dict[str, Any]) -> str:
    folder = ensure_profile_dir(user["id"])
    ensure_avatar_file(user["id"], user.get("username") or user["id"])
    return folder


def _cleanup_legacy_profile_dirs() -> None:
    if not os.path.isdir(USERS_DIR):
        return
    with get_conn() as conn:
        valid = {r["id"] for r in conn.execute("SELECT id FROM users")}
    for name in os.listdir(USERS_DIR):
        path = os.path.join(USERS_DIR, name)
        if not os.path.isdir(path):
            continue
        if name not in valid:
            shutil.rmtree(path, ignore_errors=True)


def seed_demo_users() -> None:
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count:
        return
    for name in ("张三", "李四", "王五", "赵六"):
        try:
            create_user(name, "123456")
            print(f"[OK] demo user: {name}")
        except Exception as e:
            print(f"[WARN] demo user {name} failed: {e}")


def bootstrap() -> None:
    init_db()
    seed_demo_users()
    _cleanup_legacy_profile_dirs()
