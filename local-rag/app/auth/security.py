"""JWT + 角色 + 文档级 ACL"""
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

import jwt
from fastapi import Header, HTTPException, status, Depends

from app.core.config import JWT_SECRET, JWT_ALG, JWT_TTL_HOURS
from app.db.database import get_conn, verify_password


def make_token(user_id: int, username: str, role: str) -> str:
    payload = {
        "uid": user_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")


def login(username: str, password: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role FROM users WHERE username=?",
            (username,),
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    token = make_token(row["id"], row["username"], row["role"])
    return {"token": token, "user": {"id": row["id"], "username": row["username"], "role": row["role"]}}


def get_current_user(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    return {"id": payload["uid"], "username": payload["username"], "role": payload["role"]}


def require_role(*roles):
    """依赖：限定角色"""
    def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail=f"requires role: {roles}")
        return user
    return dep


def check_doc_access(user: dict, document_id: int, required: str = "read") -> bool:
    """admin 全通；否则查 permissions 表"""
    if user["role"] == "admin":
        return True
    perm_rank = {"read": 1, "write": 2, "owner": 3}
    need = perm_rank[required]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT permission FROM permissions WHERE user_id=? AND document_id=?",
            (user["id"], document_id),
        ).fetchone()
    if not row:
        return False
    return perm_rank[row["permission"]] >= need