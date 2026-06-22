"""Authentication helpers and profile validation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from typing import Any

from fastapi import HTTPException, Request

from . import db

TOKEN_TTL_SECONDS = 60 * 60 * 24 * 14
PHONE_RE = re.compile(r"^$|^1[3-9]\d{9}$")
EMAIL_RE = re.compile(r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$")
AVATAR_MAX_CHARS = 300_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return "pbkdf2_sha256$200000$" + base64.b64encode(salt).decode("ascii") + "$" + base64.b64encode(digest).decode("ascii")


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_b64, digest_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:  # noqa: BLE001
        return False


def validate_account(account: str) -> str:
    value = account.strip()
    if EMAIL_RE.fullmatch(value):
        return value.lower()
    if PHONE_RE.fullmatch(value):
        return value
    raise HTTPException(400, "账号必须是有效邮箱或中国大陆手机号。")


def validate_password(password: str) -> str:
    if len(password) < 8:
        raise HTTPException(400, "密码至少需要 8 位。")
    if len(password) > 128:
        raise HTTPException(400, "密码长度不能超过 128 位。")
    return password


def validate_required_text(value: Any, label: str, *, max_len: int = 80) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(400, f"{label}为必填项。")
    if len(text) > max_len:
        raise HTTPException(400, f"{label}不能超过 {max_len} 个字符。")
    return text


def validate_optional_text(value: Any, label: str, *, max_len: int = 160) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > max_len:
        raise HTTPException(400, f"{label}不能超过 {max_len} 个字符。")
    return text


def validate_avatar(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > AVATAR_MAX_CHARS:
        raise HTTPException(400, "头像图片过大。")
    if not text.startswith("data:image/"):
        raise HTTPException(400, "头像必须是图片 data URL。")
    return text


def validate_contact_fields(payload: dict) -> dict[str, str | None]:
    phone = validate_optional_text(payload.get("phone"), "手机号", max_len=20)
    email = validate_optional_text(payload.get("email"), "邮箱", max_len=120)
    if phone and not PHONE_RE.fullmatch(phone):
        raise HTTPException(400, "手机号格式不正确。")
    if email and not EMAIL_RE.fullmatch(email):
        raise HTTPException(400, "邮箱格式不正确。")
    return {
        "phone": phone,
        "email": email,
        "company": validate_optional_text(payload.get("company"), "公司", max_len=120),
        "title": validate_optional_text(payload.get("title"), "职位", max_len=120),
        "bio": validate_optional_text(payload.get("bio"), "简介", max_len=500),
    }


def validate_china_id_card(id_card: Any) -> str:
    value = str(id_card or "").strip().upper()
    if not re.fullmatch(r"\d{17}[\dX]", value):
        raise HTTPException(400, "身份证号格式不正确。")
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    checks = "10X98765432"
    birth = value[6:14]
    try:
        year, month, day = int(birth[:4]), int(birth[4:6]), int(birth[6:8])
        import datetime as _dt

        born = _dt.date(year, month, day)
        if born > _dt.date.today() or year < 1900:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "身份证号出生日期不正确。") from None
    total = sum(int(value[i]) * weights[i] for i in range(17))
    if checks[total % 11] != value[-1]:
        raise HTTPException(400, "身份证号校验位不正确。")
    return value


def mask_id_card(id_card: str) -> str:
    return id_card[:5] + "*" * max(0, len(id_card) - 9) + id_card[-4:]


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "account": user["account"],
        "username": user["username"],
        "real_name": user["real_name"],
        "id_card_masked": mask_id_card(user["id_card"]),
        "avatar": user.get("avatar"),
        "phone": user.get("phone"),
        "email": user.get("email"),
        "company": user.get("company"),
        "title": user.get("title"),
        "bio": user.get("bio"),
    }


def issue_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    db.create_auth_token(user_id, token, time.time() + TOKEN_TTL_SECONDS)
    return token


def token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = request.query_params.get("token")
    return token.strip() if token else None


def require_user(request: Request) -> dict:
    token = token_from_request(request)
    if not token:
        raise HTTPException(401, "Authentication required.")
    user = db.get_user_by_token(token)
    if user is None:
        raise HTTPException(401, "Invalid or expired token.")
    return user
