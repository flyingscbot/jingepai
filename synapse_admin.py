"""Synapse Admin API helpers（实训：金格改用户名/头像时同步 Matrix）。

鉴权优先级：
  1) 环境变量 SYNAPSE_ADMIN_ACCESS_TOKEN
  2) 本地缓存 token（matrix/data/jingepi-admin.access_token）
  3) 用 registration_shared_secret 注册 @jingepi-admin 并缓存 token

Admin API 可绕过 enable_set_displayname / enable_set_avatar_url=false。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request

import auth_config
import user_db

logger = logging.getLogger(__name__)

_ADMIN_LOCALPART = "jingepi-admin"
_TOKEN_CACHE = auth_config.BASE_DIR / "matrix" / "data" / "jingepi-admin.access_token"
_ADMIN_PASSWORD = "jingepi-admin-lab-only-change-me"

_AVATAR_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}

# Synapse/Matrix 客户端对 SVG 缩略图支持很差（thumbnail 常 400 → 头像裂图），
# 上传到 Matrix 前须栅格化为 PNG。
_MATRIX_SAFE_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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


def _http_upload(
    url: str,
    data: bytes,
    content_type: str,
    token: str,
    timeout: float = 30.0,
) -> tuple[int, dict | list | None, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": content_type or "application/octet-stream",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
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


def _avatar_local_path(user_id: str) -> tuple[str | None, str | None]:
    """返回 (绝对路径, 文件名)；无本地头像时 (None, None)。"""
    name = user_db.find_avatar_filename(user_id)
    if not name:
        return None, None
    path = os.path.join(user_db.USERS_DIR, user_db.profile_dir_for(user_id), name)
    if not os.path.isfile(path):
        return None, None
    return path, name


def _mime_for_avatar(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in _AVATAR_MIME:
        return _AVATAR_MIME[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _pillow_initials_png(user_id: str, size: int = 256) -> bytes:
    """无法转换 SVG 时的兜底：纯色圆底 + 首字。"""
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    username = ""
    try:
        user = user_db.get_user_by_id(user_id)
        if user:
            username = str(user.get("username") or "")
    except Exception:
        pass
    label = (username or user_id or "?").strip()[:1] or "?"

    # 稳定色：由 user_id 派生
    h = int(hashlib.md5(user_id.encode("utf-8")).hexdigest()[:6], 16)
    fill = ((h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF, 255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size - 1, size - 1), fill=fill)
    try:
        font = ImageFont.truetype("msyh.ttc", size // 2)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", size // 2)
        except OSError:
            font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        label,
        fill=(255, 246, 209, 255),
        font=font,
    )
    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _svg_to_png_for_matrix(user_id: str, svg_path: str) -> bytes:
    """把金格 SVG 头像变成 Matrix 可用的 PNG 字节。

    优先按用户名拉 DiceBear PNG（与默认头像同源）；失败则用 Pillow 首字图。
    """
    username = ""
    try:
        user = user_db.get_user_by_id(user_id)
        if user:
            username = str(user.get("username") or "")
    except Exception:
        pass
    seed = urllib.parse.quote(username or user_id or "guest")
    remote = f"https://api.dicebear.com/7.x/avataaars/png?seed={seed}&size=256"
    try:
        with urllib.request.urlopen(remote, timeout=15) as resp:
            data = resp.read()
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return data
    except Exception as exc:
        logger.info("DiceBear PNG 拉取失败，改用首字头像: %s", exc)
    return _pillow_initials_png(user_id)


def _matrix_upload_payload(
    user_id: str, path: str, filename: str
) -> tuple[bytes, str, str]:
    """返回 (bytes, content_type, upload_filename)，保证 Matrix 可缩略图。"""
    ext = os.path.splitext(filename)[1].lower()
    with open(path, "rb") as fh:
        data = fh.read()
    if ext in _MATRIX_SAFE_AVATAR_EXT and ext != ".svg":
        return data, _mime_for_avatar(filename), filename
    # SVG（或其它不安全类型）→ PNG
    logger.info("Matrix 头像将 SVG/非安全格式栅格化为 PNG: %s", path)
    png = _svg_to_png_for_matrix(user_id, path)
    return png, "image/png", "avatar.png"


def upload_media(data: bytes, content_type: str, filename: str, token: str) -> str | None:
    """上传字节到 Synapse 媒体库，成功返回 mxc:// URI。"""
    q = urllib.parse.urlencode({"filename": filename})
    url = f"{_synapse_base()}/_matrix/media/v3/upload?{q}"
    code, body, raw = _http_upload(url, data, content_type, token)
    if code not in (200, 201) or not isinstance(body, dict) or not body.get("content_uri"):
        # 兼容旧路径
        url_r0 = f"{_synapse_base()}/_matrix/media/r0/upload?{q}"
        code, body, raw = _http_upload(url_r0, data, content_type, token)
    if code in (200, 201) and isinstance(body, dict):
        mxc = body.get("content_uri")
        if isinstance(mxc, str) and mxc.startswith("mxc://"):
            return mxc
    logger.warning("媒体上传失败: %s %s", code, (raw or "")[:200])
    return None


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
        try:
            ensure_fluffy_wallpaper_for_mxid(mxid)
        except Exception as exc:
            logger.warning("displayname 后写壁纸失败: %s", exc)
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
                try:
                    ensure_fluffy_wallpaper_for_mxid(mxid)
                except Exception as exc:
                    logger.warning("displayname 后写壁纸失败: %s", exc)
                return True
            logger.warning("displayname 同步重试失败: %s %s", code2, raw2[:200])
            return False

    logger.warning("displayname 同步失败: %s %s %s", mxid, code, raw[:200])
    return False


def set_avatar(user_id: str, local_path: str | None = None) -> bool:
    """把金格本地头像上传到 Synapse 媒体库，并设为该用户 Matrix avatar。

    user_id = 金格 users.id（hex）。成功 True；Synapse 未起 / 无 admin /
    用户尚未 SSO 创建 / 无本地文件时返回 False（不抛）。
    """
    try:
        localpart = auth_config.matrix_localpart_from_user_id(user_id)
    except ValueError as exc:
        logger.warning("set_avatar: %s", exc)
        return False

    path = local_path
    filename = None
    if path:
        if not os.path.isfile(path):
            logger.warning("set_avatar: 文件不存在 %s", path)
            return False
        filename = os.path.basename(path)
    else:
        path, filename = _avatar_local_path(user_id)
        if not path or not filename:
            logger.info("无本地头像，跳过 Matrix avatar 同步: %s", user_id)
            return False

    mxid = auth_config.matrix_mxid(localpart)
    token = ensure_admin_token()
    if not token:
        logger.warning("无 Synapse admin token，跳过 avatar 同步: %s", mxid)
        return False

    try:
        data, content_type, filename = _matrix_upload_payload(user_id, path, filename)
    except OSError as exc:
        logger.warning("读取头像失败 %s: %s", path, exc)
        return False
    if not data:
        logger.warning("头像文件为空: %s", path)
        return False

    mxc = upload_media(data, content_type, filename, token)
    if not mxc:
        return False

    url = (
        f"{_synapse_base()}/_synapse/admin/v2/users/"
        f"{urllib.parse.quote(mxid, safe='')}"
    )
    code, body, raw = _http_json(
        "PUT",
        url,
        body={"avatar_url": mxc},
        token=token,
    )
    if code in (200, 201):
        logger.info("已同步 Matrix avatar %s → %s", mxid, mxc)
        return True

    errcode = body.get("errcode") if isinstance(body, dict) else None
    if code == 404 or errcode == "M_NOT_FOUND":
        logger.info("Matrix 用户尚未存在，跳过 avatar：%s", mxid)
        return False

    if code in (401, 403):
        if _TOKEN_CACHE.is_file() and not auth_config.SYNAPSE_ADMIN_ACCESS_TOKEN:
            try:
                _TOKEN_CACHE.unlink()
            except OSError:
                pass
        token2 = ensure_admin_token()
        if token2 and token2 != token:
            mxc2 = upload_media(data, content_type, filename, token2) or mxc
            code2, _, raw2 = _http_json(
                "PUT", url, body={"avatar_url": mxc2}, token=token2
            )
            if code2 in (200, 201):
                logger.info("已同步 Matrix avatar %s → %s", mxid, mxc2)
                return True
            logger.warning("avatar 同步重试失败: %s %s", code2, raw2[:200])
            return False

    logger.warning("avatar 同步失败: %s %s %s", mxid, code, raw[:200])
    return False


def sync_avatars_from_disk() -> dict:
    """把 users/<id>/avatar.* 重新上传到 Synapse，供修复裂图后补齐。

    仅处理本地有头像文件、且 Matrix 用户已存在的账号。
    返回 {"ok": [...user_id], "skip": [...], "fail": [...]}。
    """
    result: dict[str, list[str]] = {"ok": [], "skip": [], "fail": []}
    if not os.path.isdir(user_db.USERS_DIR):
        return result
    for name in sorted(os.listdir(user_db.USERS_DIR)):
        if not isinstance(name, str) or len(name) != 32:
            continue
        if not user_db.find_avatar_filename(name):
            continue
        try:
            localpart = auth_config.matrix_localpart_from_user_id(name)
        except ValueError:
            result["skip"].append(name)
            continue
        mxid = auth_config.matrix_mxid(localpart)
        token = ensure_admin_token()
        if not token:
            result["fail"].append(name)
            continue
        code, _, _ = _http_json(
            "GET",
            f"{_synapse_base()}/_synapse/admin/v2/users/"
            f"{urllib.parse.quote(mxid, safe='')}",
            token=token,
        )
        if code == 404:
            result["skip"].append(name)
            continue
        if set_avatar(name):
            result["ok"].append(name)
        else:
            result["fail"].append(name)
    logger.info(
        "sync_avatars_from_disk ok=%s skip=%s fail=%s",
        len(result["ok"]),
        len(result["skip"]),
        len(result["fail"]),
    )
    return result


def set_deactivated(user_id: str, deactivated: bool = True) -> bool:
    """用 Admin API 停用/恢复 Matrix 用户。user_id = 金格 users.id（hex）。

    成功 True；Synapse 未起 / 无 admin / 用户尚未 SSO 创建时返回 False（不抛）。
    """
    try:
        localpart = auth_config.matrix_localpart_from_user_id(user_id)
    except ValueError as exc:
        logger.warning("set_deactivated: %s", exc)
        return False

    mxid = auth_config.matrix_mxid(localpart)
    token = ensure_admin_token()
    if not token:
        logger.warning("无 Synapse admin token，跳过 Matrix 停用: %s", mxid)
        return False

    url = (
        f"{_synapse_base()}/_synapse/admin/v2/users/"
        f"{urllib.parse.quote(mxid, safe='')}"
    )
    code, body, raw = _http_json(
        "PUT",
        url,
        body={"deactivated": bool(deactivated)},
        token=token,
    )
    if code in (200, 201):
        logger.info(
            "已%s Matrix 用户 %s",
            "停用" if deactivated else "恢复",
            mxid,
        )
        return True

    errcode = body.get("errcode") if isinstance(body, dict) else None
    if code == 404 or errcode == "M_NOT_FOUND":
        logger.info("Matrix 用户尚未存在，跳过停用：%s", mxid)
        return False

    logger.warning("Matrix 停用同步失败: %s %s %s", mxid, code, raw[:200])
    return False


# 金格Pi FluffyChat 聊天壁纸（主站同款炭黑+双光晕+网格）
_WALLPAPER_PNG = auth_config.BASE_DIR / "matrix" / "fluffy-static" / "jingepi-chat-wallpaper.png"
_WALLPAPER_MXC_CACHE = auth_config.BASE_DIR / "matrix" / "data" / "jingepi-wallpaper.mxc"
_FLUFFY_ACCOUNT_CONFIG = "im.fluffychat.account_config"
_WALLPAPER_OPACITY = 1.0
_WALLPAPER_BLUR = 0.0
# mxid → 已写入的 wallpaper mxc（进程内防抖）
_wallpaper_ensured: dict[str, str] = {}


def _read_wallpaper_mxc_cache() -> str | None:
    try:
        if _WALLPAPER_MXC_CACHE.is_file():
            mxc = _WALLPAPER_MXC_CACHE.read_text(encoding="utf-8").strip()
            if mxc.startswith("mxc://"):
                return mxc
    except OSError:
        pass
    return None


def _write_wallpaper_mxc_cache(mxc: str) -> None:
    try:
        _WALLPAPER_MXC_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _WALLPAPER_MXC_CACHE.write_text(mxc.strip() + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("无法写入 wallpaper mxc 缓存: %s", exc)


def ensure_wallpaper_mxc() -> str | None:
    """上传金格壁纸 PNG 到 Synapse 媒体库，返回 mxc://（带磁盘缓存）。"""
    cached = _read_wallpaper_mxc_cache()
    if cached:
        return cached
    token = ensure_admin_token()
    if not token:
        logger.warning("无 Synapse admin token，无法上传 Fluffy 壁纸")
        return None
    if not _WALLPAPER_PNG.is_file():
        logger.warning("壁纸文件不存在: %s", _WALLPAPER_PNG)
        return None
    try:
        data = _WALLPAPER_PNG.read_bytes()
    except OSError as exc:
        logger.warning("读取壁纸失败: %s", exc)
        return None
    if not data:
        return None
    mxc = upload_media(data, "image/png", "jingepi-chat-wallpaper.png", token)
    if mxc:
        _write_wallpaper_mxc_cache(mxc)
        logger.info("已上传 Fluffy 壁纸 %s", mxc)
    return mxc


def _login_as_user(mxid: str, admin_token: str) -> str | None:
    """Admin API：以目标用户身份签发临时 access_token。"""
    url = (
        f"{_synapse_base()}/_synapse/admin/v1/users/"
        f"{urllib.parse.quote(mxid, safe='')}/login"
    )
    code, body, raw = _http_json("POST", url, body={}, token=admin_token)
    if code in (200, 201) and isinstance(body, dict):
        tok = body.get("access_token")
        if isinstance(tok, str) and tok:
            return tok
    logger.warning("login-as 失败 %s: %s %s", mxid, code, (raw or "")[:200])
    return None


def _get_fluffy_account_config(mxid: str, admin_token: str) -> dict | None:
    url = (
        f"{_synapse_base()}/_synapse/admin/v1/users/"
        f"{urllib.parse.quote(mxid, safe='')}/accountdata"
    )
    code, body, _ = _http_json("GET", url, token=admin_token)
    if code != 200 or not isinstance(body, dict):
        return None
    account = body.get("account_data")
    if not isinstance(account, dict):
        return None
    global_data = account.get("global")
    if not isinstance(global_data, dict):
        return None
    cfg = global_data.get(_FLUFFY_ACCOUNT_CONFIG)
    return cfg if isinstance(cfg, dict) else None


def _put_fluffy_wallpaper(mxid: str, user_token: str, mxc: str) -> bool:
    url = (
        f"{_synapse_base()}/_matrix/client/v3/user/"
        f"{urllib.parse.quote(mxid, safe='')}/account_data/"
        f"{urllib.parse.quote(_FLUFFY_ACCOUNT_CONFIG, safe='')}"
    )
    payload = {
        "wallpaper_url": mxc,
        "wallpaper_opacity": _WALLPAPER_OPACITY,
        "wallpaper_blur": _WALLPAPER_BLUR,
    }
    code, _, raw = _http_json("PUT", url, body=payload, token=user_token)
    if code in (200, 201):
        return True
    logger.warning("写入 Fluffy account_config 失败 %s: %s %s", mxid, code, (raw or "")[:200])
    return False


def ensure_fluffy_wallpaper_for_mxid(mxid: str, *, force: bool = False) -> bool:
    """确保该 Matrix 用户的 FluffyChat 聊天壁纸为金格主站同款。

    壁纸存在 account_data ``im.fluffychat.account_config``（mxc URI），
    CSS 无法盖住 CanvasKit 画布；须走客户端壁纸通道。
    """
    if not isinstance(mxid, str) or not mxid.startswith("@"):
        return False
    mxc = ensure_wallpaper_mxc()
    if not mxc:
        return False
    if not force and _wallpaper_ensured.get(mxid) == mxc:
        return True

    admin_token = ensure_admin_token()
    if not admin_token:
        return False

    if not force:
        existing = _get_fluffy_account_config(mxid, admin_token)
        if (
            isinstance(existing, dict)
            and existing.get("wallpaper_url") == mxc
            and float(existing.get("wallpaper_opacity") or 0) >= 0.99
        ):
            _wallpaper_ensured[mxid] = mxc
            return True

    user_token = _login_as_user(mxid, admin_token)
    if not user_token:
        return False
    ok = _put_fluffy_wallpaper(mxid, user_token, mxc)
    if ok:
        _wallpaper_ensured[mxid] = mxc
        logger.info("已设置 Fluffy 壁纸 %s → %s", mxid, mxc)
    return ok


def ensure_fluffy_wallpaper(user_id: str, *, force: bool = False) -> bool:
    """金格 users.id → 写入 FluffyChat 壁纸 account_data。"""
    try:
        localpart = auth_config.matrix_localpart_from_user_id(user_id)
    except ValueError as exc:
        logger.warning("ensure_fluffy_wallpaper: %s", exc)
        return False
    return ensure_fluffy_wallpaper_for_mxid(
        auth_config.matrix_mxid(localpart), force=force
    )


def erase_user(user_id: str) -> bool:
    """硬删除场景：尽量擦除/停用 Matrix 用户。

    优先 POST /_synapse/admin/v1/deactivate/{userId} + erase；
    失败则回退 set_deactivated。用户尚未 SSO 创建时返回 False（不抛）。
    """
    try:
        localpart = auth_config.matrix_localpart_from_user_id(user_id)
    except ValueError as exc:
        logger.warning("erase_user: %s", exc)
        return False

    mxid = auth_config.matrix_mxid(localpart)
    token = ensure_admin_token()
    if not token:
        logger.warning("无 Synapse admin token，跳过 Matrix 擦除: %s", mxid)
        return False

    url = (
        f"{_synapse_base()}/_synapse/admin/v1/deactivate/"
        f"{urllib.parse.quote(mxid, safe='')}"
    )
    code, body, raw = _http_json(
        "POST",
        url,
        body={"erase": True},
        token=token,
    )
    if code in (200, 201):
        logger.info("已擦除 Matrix 用户 %s", mxid)
        return True

    errcode = body.get("errcode") if isinstance(body, dict) else None
    if code == 404 or errcode == "M_NOT_FOUND":
        logger.info("Matrix 用户尚未存在，跳过擦除：%s", mxid)
        return False

    logger.warning(
        "Matrix erase 失败，回退 deactivated: %s %s %s", mxid, code, raw[:200]
    )
    return set_deactivated(user_id, deactivated=True)
