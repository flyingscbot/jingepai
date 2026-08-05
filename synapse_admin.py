"""Synapse Admin API helpers（实训：金格用户名变更时同步 Matrix displayname）。

鉴权优先级：
  1) 环境变量 SYNAPSE_ADMIN_ACCESS_TOKEN
  2) 本地缓存 token（matrix/data/jingepi-admin.access_token）
  3) 用 registration_shared_secret 注册 @jingepi-admin 并缓存 token

Admin API 可绕过 enable_set_displayname=false。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

import auth_config

logger = logging.getLogger(__name__)

_ADMIN_LOCALPART = "jingepi-admin"
_TOKEN_CACHE = auth_config.BASE_DIR / "matrix" / "data" / "jingepi-admin.access_token"
_ADMIN_PASSWORD = "jingepi-admin-lab-only-change-me"


def _synapse_base() -> str:
    return auth_config.SYNAPSE_UPSTREAM.rstrip("/")


def _admin_mxid() -> str:
    return auth_config.matrix_mxid(_ADMIN_LOCALPART)


def _read_cached_token() -> str | None:
    env = (auth_config.SYNAPSE_ADMIN_ACCESS_TOKEN or "").strip()
    if env:
        return env
    try:
        if _TOKEN_CACHE.is_file():
            tok = _TOKEN_CACHE.read_text(encoding="utf-8").strip()
            return tok or None
    except OSError:
        pass
    return None


def _write_cached_token(token: str) -> None:
    try:
        _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE.write_text(token.strip() + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("无法写入 Synapse admin token 缓存: %s", exc)


def _hmac_mac(nonce: str, user: str, password: str, admin: bool) -> str:
    secret = auth_config.SYNAPSE_REGISTRATION_SHARED_SECRET.encode("utf-8")
    want_admin = b"admin" if admin else b"notadmin"
    msg = b"\x00".join(
        [
            nonce.encode("utf-8"),
            user.encode("utf-8"),
            password.encode("utf-8"),
            want_admin,
        ]
    )
    return hmac.new(secret, msg, hashlib.sha1).hexdigest()


def _http_json(
    method: str,
    url: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict | list | None, str]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else None
            return resp.status, parsed, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            parsed = None
        return e.code, parsed, raw
    except Exception as exc:
        return 0, None, str(exc)


def ensure_admin_token() -> str | None:
    """返回可用的 Synapse admin access_token；失败返回 None。"""
    cached = _read_cached_token()
    if cached:
        # 轻量自检：能列出自己即视为有效
        code, _, _ = _http_json(
            "GET",
            f"{_synapse_base()}/_synapse/admin/v2/users/{urllib.parse.quote(_admin_mxid(), safe='')}",
            token=cached,
        )
        if code == 200:
            return cached
        if code not in (401, 403):
            # 用户可能尚未创建，token 仍可能有效；继续尝试注册
            pass
        elif auth_config.SYNAPSE_ADMIN_ACCESS_TOKEN:
            logger.warning("SYNAPSE_ADMIN_ACCESS_TOKEN 无效（HTTP %s）", code)

    if not auth_config.SYNAPSE_REGISTRATION_SHARED_SECRET:
        logger.warning("未配置 SYNAPSE_REGISTRATION_SHARED_SECRET，无法自动创建 admin")
        return cached  # 可能仍可用

    code, nonce_body, raw = _http_json(
        "GET", f"{_synapse_base()}/_synapse/admin/v1/register"
    )
    if code != 200 or not isinstance(nonce_body, dict) or not nonce_body.get("nonce"):
        logger.warning("获取 Synapse register nonce 失败: %s %s", code, raw[:200])
        return cached

    nonce = str(nonce_body["nonce"])
    mac = _hmac_mac(nonce, _ADMIN_LOCALPART, _ADMIN_PASSWORD, admin=True)
    code, reg_body, raw = _http_json(
        "POST",
        f"{_synapse_base()}/_synapse/admin/v1/register",
        body={
            "nonce": nonce,
            "username": _ADMIN_LOCALPART,
            "displayname": "金格Pi Admin",
            "password": _ADMIN_PASSWORD,
            "admin": True,
            "mac": mac,
        },
    )
    if code in (200, 201) and isinstance(reg_body, dict) and reg_body.get("access_token"):
        token = str(reg_body["access_token"])
        _write_cached_token(token)
        logger.info("已创建/注册 Synapse admin %s", _admin_mxid())
        return token

    # User already exists → shared-secret register 无法再拿 token
    err = ""
    if isinstance(reg_body, dict):
        err = str(reg_body.get("error") or reg_body.get("errcode") or "")
    logger.warning(
        "Synapse admin 注册失败（若账号已存在请配置 SYNAPSE_ADMIN_ACCESS_TOKEN "
        "或删除缓存后见 SETUP）: %s %s %s",
        code,
        err,
        raw[:200],
    )
    return cached


def set_displayname(user_id: str, displayname: str) -> bool:
    """用 Admin API 设置 Matrix 用户显示名。user_id = 金格 users.id（hex）。

    成功 True；Synapse 未起 / 无 admin / 用户尚未 SSO 创建时返回 False（不抛）。
    """
    try:
        localpart = auth_config.matrix_localpart_from_user_id(user_id)
    except ValueError as exc:
        logger.warning("set_displayname: %s", exc)
        return False

    mxid = auth_config.matrix_mxid(localpart)
    token = ensure_admin_token()
    if not token:
        logger.warning("无 Synapse admin token，跳过 displayname 同步: %s", mxid)
        return False

    url = (
        f"{_synapse_base()}/_synapse/admin/v2/users/"
        f"{urllib.parse.quote(mxid, safe='')}"
    )
    code, body, raw = _http_json(
        "PUT",
        url,
        body={"displayname": displayname},
        token=token,
    )
    if code in (200, 201):
        logger.info("已同步 Matrix displayname %s → %s", mxid, displayname)
        return True

    # 用户尚未在 Synapse 创建（未 SSO）——可忽略
    errcode = body.get("errcode") if isinstance(body, dict) else None
    if code == 404 or errcode == "M_NOT_FOUND":
        logger.info("Matrix 用户尚未存在，跳过 displayname：%s", mxid)
        return False

    if code in (401, 403):
        # 清缓存后重试一次（可能 token 过期且可重新注册）
        if _TOKEN_CACHE.is_file() and not auth_config.SYNAPSE_ADMIN_ACCESS_TOKEN:
            try:
                _TOKEN_CACHE.unlink()
            except OSError:
                pass
        token2 = ensure_admin_token()
        if token2 and token2 != token:
            code2, _, raw2 = _http_json(
                "PUT", url, body={"displayname": displayname}, token=token2
            )
            if code2 in (200, 201):
                logger.info("已同步 Matrix displayname %s → %s", mxid, displayname)
                return True
            logger.warning("displayname 同步重试失败: %s %s", code2, raw2[:200])
            return False

    logger.warning("displayname 同步失败: %s %s %s", mxid, code, raw[:200])
    return False
