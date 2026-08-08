# -*- coding: utf-8 -*-
"""
房间自动分配器
===============
根据 users.db 中 users 表的 suggested_room_type 字段，
自动将用户添加到对应的 Matrix 房间，并移除不属于该房间的用户。

策略：
- 遍历每个房间，找到房间内权限最高的成员作为 operator
- 使用该 operator 的 token 进行 invite/kick 操作
- 使用目标用户自身的 token 进行 self-join 操作
- 每 30 秒执行一次全量同步

启动方式：
    venv\\Scripts\\python.exe room_allocator.py --once     # 执行一次
    venv\\Scripts\\python.exe room_allocator.py            # 守护进程模式
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import auth_config
import user_db
import synapse_admin

logger = logging.getLogger("room_allocator")
logger.setLevel(logging.INFO)

if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)

    _log_dir = Path("logs")
    _log_dir.mkdir(exist_ok=True)
    _fh = logging.FileHandler(_log_dir / "room_allocator.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)

CHECK_INTERVAL = 5

ROOM_MAPPING_FILE = Path(__file__).parent / "room.json"

# 管理员 MXID，用于快速获取 token
ADMIN_MXID = auth_config.matrix_mxid("jingepi-admin")


def _upstream(path: str) -> str:
    return f"{auth_config.SYNAPSE_UPSTREAM.rstrip('/')}{path}"


def _request(url: str, token: str | None = None, data: bytes | None = None, method: str = "GET") -> urllib.request.Request:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=data, headers=headers, method=method)


def load_room_mapping() -> dict[str, dict[str, str]]:
    with open(ROOM_MAPPING_FILE, encoding="utf-8") as f:
        raw = json.load(f)
    # 过滤以 _ 开头的元数据 key（如 _global_space），仅返回 room_type → room_info
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def load_global_space() -> dict[str, str] | None:
    """读取全员空间配置（room.json 的 _global_space）。

    所有活跃用户都会被自动加入该空间，不区分角色 / MBTI 类型。
    """
    try:
        with open(ROOM_MAPPING_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return None
    space = raw.get("_global_space")
    if not isinstance(space, dict) or not space.get("room_id"):
        return None
    return space


def get_user_mxid(user_id: str) -> str:
    if user_id.startswith("@"):
        return user_id
    localpart = auth_config.matrix_localpart_from_user_id(user_id)
    return auth_config.matrix_mxid(localpart)


def get_user_room_types(user: dict[str, Any]) -> list[str]:
    # 管理员（admin / super_admin）与专家（specialist）强制加入全部房间
    # 兜底：即便 suggested_room_type 未同步，也按 role 直接判定
    role = (user.get("role") or "").strip().lower()
    if role in ("admin", "super_admin", "specialist"):
        return list(load_room_mapping().keys())
    suggested = (user.get("suggested_room_type") or "").strip().upper()
    if not suggested:
        return []
    if suggested == "ALL":
        return list(load_room_mapping().keys())
    types = []
    for rt in suggested.split(","):
        rt = rt.strip().upper()
        if rt and rt in load_room_mapping():
            types.append(rt)
    return types


def get_user_token(mxid: str, admin_token: str) -> str | None:
    if mxid == ADMIN_MXID:
        return admin_token  # admin 自己，直接返回 admin token
    
    try:
        url = _upstream(f"/_synapse/admin/v1/users/{mxid}/login")
        req = _request(url, admin_token, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        if "Cannot use admin API to login as self" in body:
            return admin_token  # admin 自身
        logger.error("获取用户 %s token 失败: HTTP %s - %s", mxid, e.code, body)
        return None
    except Exception as e:
        logger.error("获取用户 %s token 异常: %s", mxid, e)
        return None


def get_room_members(room_id: str, admin_token: str) -> set[str]:
    """获取房间成员列表"""
    try:
        url = _upstream(f"/_synapse/admin/v1/rooms/{room_id}/members")
        req = _request(url, admin_token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return set(data.get("members", []))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        if e.code == 404 or "M_NOT_FOUND" in body:
            logger.warning("房间 %s 不存在", room_id)
        else:
            logger.error("获取房间 %s 成员失败: HTTP %s - %s", room_id, e.code, body)
        return set()
    except Exception as e:
        logger.error("获取房间 %s 成员异常: %s", room_id, e)
        return set()


def get_room_power_levels(room_id: str, token: str) -> dict[str, Any] | None:
    """获取房间的 power_levels 状态"""
    try:
        url = _upstream(f"/_matrix/client/v3/rooms/{room_id}/state/m.room.power_levels")
        req = _request(url, token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("content", {})
    except Exception as e:
        logger.debug("获取房间 %s power_levels 失败: %s", room_id, e)
        return None


def get_room_creator(room_id: str, admin_token: str) -> str | None:
    """获取房间创建者的 MXID"""
    try:
        url = _upstream(f"/_synapse/admin/v1/rooms/{room_id}")
        req = _request(url, admin_token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("creator")
    except Exception as e:
        logger.debug("获取房间 %s 创建者失败: %s", room_id, e)
        return None


def find_room_operator(room_id: str, admin_token: str) -> str | None:
    """找到房间中权限最高的成员作为 operator，返回其 token
    
    策略：
    1. 获取房间 power_levels 状态
    2. 如果状态为空，使用默认 Matrix 规则：创建者 power=100，其他成员 power=0
    3. 找到权限 >= invite/kick 要求的成员
    4. 如果 admin 是唯一合格者，使用 admin token
    """
    members = get_room_members(room_id, admin_token)
    if not members:
        return None

    # 获取房间 power_levels
    power_content = get_room_power_levels(room_id, admin_token)
    
    if power_content is None or not power_content:
        # power_levels 为空或获取失败，使用默认规则
        # 房间创建者 power=100，其他成员 power=0
        creator = get_room_creator(room_id, admin_token)
        if creator and creator in members:
            logger.info("房间 %s 使用默认 power_levels，创建者 %s 作为 operator", room_id, creator)
            if creator == ADMIN_MXID:
                return admin_token  # admin 自己
            token = get_user_token(creator, admin_token)
            if token:
                return token
        # 回退：使用第一个成员
        for mxid in members:
            if mxid == ADMIN_MXID:
                return admin_token
            token = get_user_token(mxid, admin_token)
            if token:
                return token
        return None

    users_power = power_content.get("users", {})
    default_power = power_content.get("default", 0)
    invite_level = power_content.get("invite", 50)
    kick_level = power_content.get("kick", 50)
    required_level = max(invite_level, kick_level)

    # 找到权限满足要求的成员
    qualified: list[tuple[int, str]] = []
    for mxid in members:
        power = users_power.get(mxid, default_power)
        if power >= required_level:
            qualified.append((power, mxid))

    if not qualified:
        # 回退：使用创建者或任意成员
        creator = get_room_creator(room_id, admin_token)
        if creator and creator in members:
            logger.info("回退使用创建者 %s (power_levels 显式为空)", creator)
            if creator == ADMIN_MXID:
                return admin_token
            token = get_user_token(creator, admin_token)
            if token:
                return token
        # 最后回退：第一个成员
        logger.info("回退使用第一个成员")
        for mxid in members:
            if mxid == ADMIN_MXID:
                return admin_token
            token = get_user_token(mxid, admin_token)
            if token:
                return token
        return None

    # 按权限排序，取最高的
    qualified.sort(key=lambda x: x[0], reverse=True)
    
    for power, mxid in qualified:
        if mxid == ADMIN_MXID:
            return admin_token  # admin 自己
        token = get_user_token(mxid, admin_token)
        if token:
            logger.info("找到 operator: %s (power=%d)", mxid, power)
            return token

    return None


def invite_user_to_room(room_id: str, user_mxid: str, operator_token: str, user_token: str | None = None) -> bool:
    """邀请用户加入房间，并自动接受邀请"""
    try:
        url = _upstream(f"/_matrix/client/v3/rooms/{room_id}/invite")
        body = json.dumps({"user_id": user_mxid}).encode()
        req = _request(url, operator_token, body, "POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("邀请 %s 加入 %s 成功", user_mxid, room_id)
            # 邀请成功后，用用户自己的 token 接受邀请
            if user_token:
                time.sleep(0.5)
                url_join = _upstream(f"/_matrix/client/v3/rooms/{room_id}/join")
                req_join = _request(url_join, user_token, b"{}", "POST")
                try:
                    with urllib.request.urlopen(req_join, timeout=15) as resp2:
                        logger.info("%s 接受邀请加入 %s 成功", user_mxid, room_id)
                except urllib.error.HTTPError as e2:
                    err2 = ""
                    try:
                        err2 = e2.read().decode()[:200]
                    except Exception:
                        pass
                    if "is already in the room" not in err2:
                        logger.warning("%s 接受邀请失败: %s", user_mxid, err2)
            return True
    except urllib.error.HTTPError as e:
        err = ""
        try:
            err = e.read().decode()[:200]
        except Exception:
            pass
        if "is already in the room" in err:
            logger.debug("%s 已在 %s 中", user_mxid, room_id)
            return True
        if "not in the room" in err.lower() or "not have permission" in err.lower():
            logger.warning("operator 权限不足，无法邀请 %s 加入 %s", user_mxid, room_id)
            return False
        if e.code == 429:
            logger.warning("邀请 %s 触发限流", user_mxid)
            time.sleep(5)
            return False
        logger.error("邀请 %s 加入 %s 失败: HTTP %s - %s", user_mxid, room_id, e.code, err)
        return False
    except Exception as e:
        logger.error("邀请 %s 加入 %s 异常: %s", user_mxid, room_id, e)
        return False


def join_room(room_id: str, user_mxid: str, user_token: str) -> bool:
    """用户自己加入房间"""
    try:
        url = _upstream(f"/_matrix/client/v3/rooms/{room_id}/join")
        req = _request(url, user_token, b"{}", "POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("用户 %s 加入 %s 成功", user_mxid, room_id)
            return True
    except urllib.error.HTTPError as e:
        err = ""
        try:
            err = e.read().decode()[:200]
        except Exception:
            pass
        if "is already in the room" in err:
            logger.debug("%s 已在 %s 中", user_mxid, room_id)
            return True
        if "not invited" in err.lower() or "not allowed" in err.lower():
            return False  # 需要邀请，不能直接加入
        logger.error("%s 加入 %s 失败: HTTP %s - %s", user_mxid, room_id, e.code, err)
        return False
    except Exception as e:
        logger.error("%s 加入 %s 异常: %s", user_mxid, room_id, e)
        return False


def kick_user_from_room(room_id: str, user_mxid: str, operator_token: str) -> bool:
    """将用户从房间移除"""
    try:
        url = _upstream(f"/_matrix/client/v3/rooms/{room_id}/kick")
        body = json.dumps({
            "user_id": user_mxid,
            "reason": "用户不在该房间的分房列表中，自动移除",
        }).encode()
        req = _request(url, operator_token, body, "POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info("移除 %s 从 %s 成功", user_mxid, room_id)
            return True
    except urllib.error.HTTPError as e:
        err = ""
        try:
            err = e.read().decode()[:200]
        except Exception:
            pass
        if "not in the room" in err.lower():
            logger.debug("%s 已不在 %s 中", user_mxid, room_id)
            return True
        if "not have permission" in err.lower() or "cannot kick" in err.lower():
            logger.warning("operator 权限不足，无法移除 %s", user_mxid)
            return False
        if e.code == 429:
            logger.warning("移除 %s 触发限流", user_mxid)
            time.sleep(5)
            return False
        logger.error("移除 %s 从 %s 失败: HTTP %s - %s", user_mxid, room_id, e.code, err)
        return False
    except Exception as e:
        logger.error("移除 %s 从 %s 异常: %s", user_mxid, room_id, e)
        return False


def sync_room_assignments() -> dict[str, Any]:
    """执行全量房间分配同步"""
    admin_token = synapse_admin.ensure_admin_token()
    if not admin_token:
        logger.error("无可用的 Synapse admin token")
        return {"error": "no_admin_token"}

    room_mapping = load_room_mapping()

    # 检查有效房间
    valid_rooms: dict[str, dict[str, str]] = {}
    for rt, info in room_mapping.items():
        room_id = info["room_id"]
        members = get_room_members(room_id, admin_token)
        if members:
            valid_rooms[rt] = info
        else:
            logger.warning("房间 %s (%s) 不存在或无成员，跳过", rt, room_id)

    if not valid_rooms:
        logger.warning("无有效房间")
        return {"valid_rooms": 0}

    # 为每个房间找到 operator token
    operator_cache: dict[str, str | None] = {}
    for rt, info in valid_rooms.items():
        room_id = info["room_id"]
        operator_cache[room_id] = find_room_operator(room_id, admin_token)

    users = user_db.list_users()
    active_users = [u for u in users if u.get("is_active", True)]

    stats: dict[str, Any] = {
        "total_users": len(users),
        "active_users": len(active_users),
        "valid_rooms": len(valid_rooms),
        "invited": 0,
        "kicked": 0,
        "skipped_no_type": 0,
        "errors": 0,
    }

    user_token_cache: dict[str, str | None] = {}

    for user in active_users:
        user_id = user.get("id", "")
        suggested_type = user.get("suggested_room_type")

        if not suggested_type:
            stats["skipped_no_type"] += 1
            continue

        target_room_types = get_user_room_types(user)
        user_mxid = get_user_mxid(user_id)

        # 获取用户 token（用于 self-join）
        user_token = user_token_cache.get(user_mxid)
        if user_token is None and user_mxid not in user_token_cache:
            user_token = get_user_token(user_mxid, admin_token)
            user_token_cache[user_mxid] = user_token

        for room_type, room_info in valid_rooms.items():
            room_id = room_info["room_id"]
            should_be_in = room_type in target_room_types

            try:
                current_members = get_room_members(room_id, admin_token)
            except Exception as e:
                logger.error("获取 %s 成员异常: %s", room_id, e)
                stats["errors"] += 1
                continue

            is_in = user_mxid in current_members

            if should_be_in and not is_in:
                if user_token:
                    # 先尝试 self-join
                    if join_room(room_id, user_mxid, user_token):
                        stats["invited"] += 1
                    else:
                        # self-join 失败（房间是 invite/knock 模式），尝试 invite
                        operator_token = operator_cache.get(room_id)
                        if operator_token:
                            if invite_user_to_room(room_id, user_mxid, operator_token, user_token):
                                stats["invited"] += 1
                            else:
                                stats["errors"] += 1
                        else:
                            stats["errors"] += 1
                else:
                    stats["errors"] += 1
                
                # 小延迟避免限流
                time.sleep(0.3)

            elif not should_be_in and is_in:
                operator_token = operator_cache.get(room_id)
                if operator_token:
                    if kick_user_from_room(room_id, user_mxid, operator_token):
                        stats["kicked"] += 1
                    else:
                        stats["errors"] += 1
                else:
                    stats["errors"] += 1
                
                # 小延迟避免限流
                time.sleep(0.3)

    # 全员空间：所有活跃用户都加入（不区分角色 / MBTI 类型）
    global_space = load_global_space()
    stats["space_invited"] = 0
    if global_space:
        space_id = global_space["room_id"]
        space_members = get_room_members(space_id, admin_token)
        if space_members:
            space_operator = find_room_operator(space_id, admin_token)
            for user in active_users:
                user_id = user.get("id", "")
                user_mxid = get_user_mxid(user_id)
                if user_mxid in space_members:
                    continue
                # 获取用户 token（复用缓存，无 suggested_room_type 的用户前面未缓存）
                user_token = user_token_cache.get(user_mxid)
                if user_token is None and user_mxid not in user_token_cache:
                    user_token = get_user_token(user_mxid, admin_token)
                    user_token_cache[user_mxid] = user_token
                if user_token and join_room(space_id, user_mxid, user_token):
                    stats["space_invited"] += 1
                elif space_operator and user_token:
                    if invite_user_to_room(space_id, user_mxid, space_operator, user_token):
                        stats["space_invited"] += 1
                    else:
                        stats["errors"] += 1
                else:
                    stats["errors"] += 1
                time.sleep(0.3)
            logger.info(
                "全员空间 %s: %d 用户已加入",
                global_space.get("name", space_id),
                stats["space_invited"],
            )
        else:
            logger.warning("全员空间 %s 不存在或无成员，跳过", space_id)

    logger.info(
        "房间分配同步完成: %d 活跃用户, %d 有效房间, %d 已加入, %d 已移除, %d 无类型, %d 错误, %d 空间已加入",
        stats["active_users"],
        stats["valid_rooms"],
        stats["invited"],
        stats["kicked"],
        stats["skipped_no_type"],
        stats["errors"],
        stats["space_invited"],
    )
    return stats


def run_daemon(interval: int = CHECK_INTERVAL) -> None:
    logger.info("=" * 60)
    logger.info("房间分配守护进程启动（间隔 %d 秒）", interval)
    logger.info("=" * 60)

    running = True

    def _handle_signal(signum, frame):
        nonlocal running
        logger.info("收到信号 %s，正在退出...", signum)
        running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        sync_room_assignments()
    except Exception as e:
        logger.error("首次同步异常: %s", e)

    while running:
        try:
            time.sleep(interval)
            if not running:
                break
            sync_room_assignments()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("同步异常: %s", e)
            time.sleep(5)

    logger.info("房间分配守护进程已停止")


def run_in_thread(interval: int = CHECK_INTERVAL) -> None:
    """供 main.py 集成为 daemon 线程的房间分配循环。

    与 run_daemon 的区别：不注册 signal（Python 仅允许主线程注册信号），
    靠线程 daemon=True 在主进程退出时自动结束；无外部信号停止需求。
    """
    logger.info("=" * 60)
    logger.info("房间分配后台线程启动（间隔 %d 秒）", interval)
    logger.info("=" * 60)
    try:
        sync_room_assignments()
    except Exception as e:
        logger.error("首次同步异常: %s", e)
    while True:
        try:
            time.sleep(interval)
            sync_room_assignments()
        except Exception as e:
            logger.error("同步异常: %s", e)
            time.sleep(5)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        logger.info("单次执行模式")
        stats = sync_room_assignments()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        run_daemon()


if __name__ == "__main__":
    main()