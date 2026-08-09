"""SQLite 用户库（业界常见做法）。



- 密码：Werkzeug scrypt 单向哈希（不可逆，登录时比对哈希）

- 用户 ID：UUID4 hex，全局唯一

- 资料夹：users/<user_id>/，头像文件放资料夹，不入库

- 用户名：登录名即展示名

- 角色三级：user / admin（普通管理）/ super_admin（最高管理）

- 状态：is_active，停用后拒绝登录与 OIDC

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

DEFAULT_ROLE = "trial"

ROLE_SUPER_ADMIN = "super_admin"

ROLE_ADMIN = "admin"

ROLE_SPECIALIST = "specialist"

ROLE_USER = "user"

ROLE_TRIAL = "trial"

VALID_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_SPECIALIST, ROLE_USER, ROLE_TRIAL})

CONSOLE_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN})

ROLE_LABELS = {

    ROLE_SUPER_ADMIN: "最高管理",

    ROLE_ADMIN: "普通管理",

    ROLE_SPECIALIST: "专家",

    ROLE_USER: "用户",

    ROLE_TRIAL: "免费用户",

}

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

                is_active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))

            )

            """

        )

        cols = _table_columns(conn)

        if "role" not in cols:

            conn.execute(

                "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"

            )

        if "is_active" not in cols:

            conn.execute(

                "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"

            )

        if "created_at" not in cols:

            conn.execute(

                "ALTER TABLE users ADD COLUMN created_at TEXT "

                "NOT NULL DEFAULT (datetime('now','localtime'))"

            )

        if "suggested_room_type" not in cols:

            conn.execute(

                "ALTER TABLE users ADD COLUMN suggested_room_type TEXT"

            )

        conn.execute(

            """

            UPDATE users

            SET suggested_room_type = 'all'

            WHERE role IN ('admin', 'super_admin', 'specialist')

            """

        )

        # 仅补空角色，绝不可把已有 admin / super_admin 刷回 user

        conn.execute(

            """

            UPDATE users

            SET role = 'user'

            WHERE role IS NULL OR TRIM(role) = ''

            """

        )

        conn.execute(

            """

            UPDATE users

            SET is_active = 1

            WHERE is_active IS NULL

            """

        )

        _migrate_legacy_admins(conn)

        conn.commit()



    try:

        from room_type import sync_all_suggested_room_types

        sync_all_suggested_room_types()

    except Exception as e:

        print(f"[room_type] 批量同步 suggested_room_type 失败: {e}")





def _migrate_legacy_admins(conn: sqlite3.Connection) -> None:

    """一次性：库中尚无 super_admin 时，将旧 admin 全部升为 super_admin。



    之后新建的 admin（普通管理）不会再被误升，因为已存在最高管理。

    """

    row = conn.execute(

        "SELECT COUNT(*) AS c FROM users WHERE role = ?",

        (ROLE_SUPER_ADMIN,),

    ).fetchone()

    if int(row["c"]) > 0:

        return

    cur = conn.execute(

        "UPDATE users SET role = ? WHERE role = ?",

        (ROLE_SUPER_ADMIN, ROLE_ADMIN),

    )

    if cur.rowcount:

        print(

            f"[OK] 角色迁移：已将 {cur.rowcount} 个旧 admin 提升为 super_admin（最高管理）"

        )





def _row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:

    if row is None:

        return None

    keys = set(row.keys())

    role = row["role"] if "role" in keys and row["role"] else DEFAULT_ROLE

    if role not in VALID_ROLES:

        role = DEFAULT_ROLE

    is_active = True

    if "is_active" in keys and row["is_active"] is not None:

        is_active = bool(int(row["is_active"]))

    return {

        "id": row["id"],

        "username": row["username"],

        "password_hash": row["password_hash"],

        "role": role,

        "is_active": is_active,

        "created_at": row["created_at"] if "created_at" in keys else "",

        "suggested_room_type": row["suggested_room_type"] if "suggested_room_type" in keys else None,

    }





def public_user(user: dict[str, Any]) -> dict[str, Any]:

    """管理后台 / API 返回用，不含密码哈希。"""

    role = user.get("role") or DEFAULT_ROLE

    return {

        "id": user["id"],

        "username": user["username"],

        "role": role,

        "role_label": ROLE_LABELS.get(role, ROLE_LABELS[DEFAULT_ROLE]),

        "is_active": bool(user.get("is_active", True)),

        "created_at": user.get("created_at") or "",

        "suggested_room_type": user.get("suggested_room_type"),

    }





def normalize_role(role: str | None) -> str:

    role = (role or DEFAULT_ROLE).strip().lower()

    if role not in VALID_ROLES:

        raise ValueError(

            "角色无效，仅支持 super_admin / admin / specialist / user"

        )

    return role





def is_console_role(role: str | None) -> bool:

    return (role or "") in CONSOLE_ROLES





def is_super_admin_role(role: str | None) -> bool:

    return role == ROLE_SUPER_ADMIN



def is_specialist_role(role: str | None) -> bool:

    return role == ROLE_SPECIALIST



def should_join_all_rooms(role: str | None) -> bool:

    """管理员（admin / super_admin）与专家（specialist）加入全部主群。"""

    return is_console_role(role) or is_specialist_role(role)



def can_create_matrix_rooms(role: str | None) -> bool:
    """最高管理 / 普通管理可建群聊与空间；普通用户与专家不可。"""
    return (role or "") in CONSOLE_ROLES





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

    # 存 PNG：Synapse/Matrix 客户端对 SVG 缩略图支持差，易导致 Matrix 头像裂图
    local_path = os.path.join(USERS_DIR, folder, "avatar.png")

    remote = (
        f"https://api.dicebear.com/7.x/avataaars/png"
        f"?seed={urllib.parse.quote(seed)}&size=256"
    )

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





def set_suggested_room_type(user_id: str, room_type: str | None) -> None:

    """写入建议主群类型：all（管理员）或 C1–C5。"""

    from room_type import normalize_room_type

    value: str | None

    if room_type is None or str(room_type).strip() == "":

        value = None

    else:

        value = normalize_room_type(str(room_type))

    with get_conn() as conn:

        conn.execute(

            "UPDATE users SET suggested_room_type = ? WHERE id = ?",

            (value, user_id),

        )

        conn.commit()





def create_user(

    username: str, password: str, role: str = DEFAULT_ROLE

) -> dict[str, Any]:

    username = username.strip()

    if not username or not password:

        raise ValueError("账号密码不能为空")

    if len(username) > 32:

        raise ValueError("用户名最多 32 个字符")

    if len(password) < 6:

        raise ValueError("密码至少 6 位")

    role = normalize_role(role)

    if get_user_by_name(username):

        raise ValueError("该账号已存在")



    with get_conn() as conn:

        user_id = generate_unique_id(conn)

        ensure_profile_dir(user_id)

        ensure_avatar_file(user_id, username)

        password_hash = hash_password(password)

        from room_type import room_type_for_role

        suggested_room = room_type_for_role(role)

        conn.execute(

            """

            INSERT INTO users (id, username, password_hash, role, is_active, suggested_room_type)

            VALUES (?, ?, ?, ?, 1, ?)

            """,

            (

                user_id,

                username,

                password_hash,

                role,

                suggested_room,

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





def admin_set_password(user_id: str, new_password: str) -> None:

    """管理员重置密码（无需旧密码）。"""

    if not get_user_by_id(user_id):

        raise ValueError("用户不存在")

    if not new_password or len(new_password) < 6:

        raise ValueError("新密码至少 6 位")

    with get_conn() as conn:

        conn.execute(

            "UPDATE users SET password_hash = ? WHERE id = ?",

            (hash_password(new_password), user_id),

        )

        conn.commit()





def count_super_admins(active_only: bool = True) -> int:

    with get_conn() as conn:

        if active_only:

            row = conn.execute(

                """

                SELECT COUNT(*) AS c FROM users

                WHERE role = ? AND is_active = 1

                """,

                (ROLE_SUPER_ADMIN,),

            ).fetchone()

        else:

            row = conn.execute(

                "SELECT COUNT(*) AS c FROM users WHERE role = ?",

                (ROLE_SUPER_ADMIN,),

            ).fetchone()

        return int(row["c"])





def count_admins(active_only: bool = True) -> int:

    """兼容旧调用：统计最高管理数量（含迁移后语义）。"""

    return count_super_admins(active_only=active_only)





def _guard_last_super_admin(user: dict[str, Any], *, action: str) -> None:

    if (

        user.get("role") == ROLE_SUPER_ADMIN

        and user.get("is_active", True)

        and count_super_admins(active_only=True) <= 1

    ):

        raise ValueError(f"不能{action}唯一的最高管理")





def list_users(q: str | None = None) -> list[dict[str, Any]]:

    q = (q or "").strip()

    with get_conn() as conn:

        if q:

            rows = conn.execute(

                """

                SELECT * FROM users

                WHERE username LIKE ? ESCAPE '\\'

                ORDER BY created_at DESC, username COLLATE NOCASE

                """,

                (f"%{_like_escape(q)}%",),

            ).fetchall()

        else:

            rows = conn.execute(

                """

                SELECT * FROM users

                ORDER BY created_at DESC, username COLLATE NOCASE

                """

            ).fetchall()

    users = []

    for row in rows:

        user = _row_to_user(row)

        if user:

            users.append(public_user(user))

    return users





def _like_escape(value: str) -> str:

    return (

        value.replace("\\", "\\\\")

        .replace("%", "\\%")

        .replace("_", "\\_")

    )





def set_user_role(user_id: str, role: str) -> dict[str, Any]:

    role = normalize_role(role)

    user = get_user_by_id(user_id)

    if not user:

        raise ValueError("用户不存在")

    if user["role"] == ROLE_SUPER_ADMIN and role != ROLE_SUPER_ADMIN:

        _guard_last_super_admin(user, action="降级")

    with get_conn() as conn:

        conn.execute(

            "UPDATE users SET role = ? WHERE id = ?",

            (role, user_id),

        )

        conn.commit()



    from room_type import sync_suggested_room_type_for_user

    sync_suggested_room_type_for_user(user_id)

    updated = get_user_by_id(user_id)

    assert updated is not None

    return updated





def set_user_active(user_id: str, is_active: bool) -> dict[str, Any]:

    user = get_user_by_id(user_id)

    if not user:

        raise ValueError("用户不存在")

    if not is_active:

        _guard_last_super_admin(user, action="停用")

    with get_conn() as conn:

        conn.execute(

            "UPDATE users SET is_active = ? WHERE id = ?",

            (1 if is_active else 0, user_id),

        )

        conn.commit()

    updated = get_user_by_id(user_id)

    assert updated is not None

    return updated





def admin_update_user(

    user_id: str,

    *,

    username: str | None = None,

    password: str | None = None,

    role: str | None = None,

    is_active: bool | None = None,

) -> dict[str, Any]:

    user = get_user_by_id(user_id)

    if not user:

        raise ValueError("用户不存在")



    if username is not None:

        update_username(user_id, username)

    if password is not None and str(password).strip() != "":

        admin_set_password(user_id, password)

    if role is not None:

        set_user_role(user_id, role)

    if is_active is not None:

        set_user_active(user_id, bool(is_active))



    updated = get_user_by_id(user_id)

    assert updated is not None

    return updated





def deactivate_user(user_id: str) -> dict[str, Any]:

    """停用账号（软删除）。"""

    return set_user_active(user_id, False)





def delete_user(user_id: str) -> dict[str, Any]:

    """硬删除：从 users.db 移除并删除资料夹。禁止删除唯一最高管理。"""

    user = get_user_by_id(user_id)

    if not user:

        raise ValueError("用户不存在")

    _guard_last_super_admin(user, action="删除")

    snapshot = public_user(user)

    with get_conn() as conn:

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

        conn.commit()

    folder = os.path.join(USERS_DIR, profile_dir_for(user_id))

    if os.path.isdir(folder):

        shutil.rmtree(folder, ignore_errors=True)

    return snapshot





def promote_admin_from_env() -> None:

    """若尚无最高管理，将环境变量 JINGEPI_ADMIN_USERNAME 提升为 super_admin（仅一次）。"""

    username = (os.environ.get("JINGEPI_ADMIN_USERNAME") or "").strip()

    if not username:

        return

    if count_super_admins(active_only=False) > 0:

        return

    user = get_user_by_name(username)

    if not user:

        print(

            f"[WARN] JINGEPI_ADMIN_USERNAME={username!r} 用户不存在，跳过提升最高管理"

        )

        return

    with get_conn() as conn:

        conn.execute(

            "UPDATE users SET role = ?, is_active = 1 WHERE id = ?",

            (ROLE_SUPER_ADMIN, user["id"]),

        )

        conn.commit()

    print(f"[OK] 已将用户 {username!r} 提升为 super_admin（最高管理）")





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

    promote_admin_from_env()

    _cleanup_legacy_profile_dirs()


