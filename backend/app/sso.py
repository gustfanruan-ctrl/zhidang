# CR-FINAL-FIX: 将SSO nonce从内存集合改为数据库表防重放。
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import hashlib
import hmac
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import SsoNonceUsed


def build_sso_token(user_name: str, user_id: str, company_id: str, secret: str) -> str:
    ts = str(int(datetime.now().timestamp()))
    nonce = str(uuid4())
    raw = f'{user_name}|{user_id}|{company_id}|{ts}|{nonce}'
    sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f'{raw}|{sig}'


def verify_sso_token(token: str, company_id: str, secret: str, ttl_minutes: int, db: Session) -> dict[str, Any]:
    try:
        user_name, user_id, token_company_id, ts, nonce, sig = token.split('|')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='token 格式错误') from exc
    if token_company_id != company_id:
        raise HTTPException(status_code=403, detail='company_id 不匹配')
    raw = f'{user_name}|{user_id}|{token_company_id}|{ts}|{nonce}'
    expected_sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=403, detail='链接已失效')
    if datetime.now().timestamp() - int(ts) > ttl_minutes * 60:
        raise HTTPException(status_code=403, detail='链接已失效')
    existed = db.get(SsoNonceUsed, nonce)
    if existed:
        raise HTTPException(status_code=403, detail='链接已使用，请从简道云重新进入')
    db.add(SsoNonceUsed(nonce=nonce))
    db.commit()
    return {'user_name': user_name, 'user_id': user_id, 'company_id': company_id}
