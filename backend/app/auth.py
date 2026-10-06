"""Demo auth: log in as any Steam user id from the dataset (no passwords; this is a
demo store whose "accounts" are public dataset users).

The browser gets the JWT in an HttpOnly, SameSite=Strict cookie, so page scripts
can't read it and other sites can't send it. API clients and tests may send it as
a Bearer header instead.
"""
import os
import time

import jwt
from fastapi import Cookie, Header, HTTPException

COOKIE = "respawn_session"
TTL = 86400
SECRET = os.environ.get("JWT_SECRET")
if not SECRET:
    if os.environ.get("RESPAWN_ENV", "dev") != "dev":
        raise RuntimeError("JWT_SECRET must be set outside dev")
    SECRET = "dev-only-secret-not-for-production-use"


def issue(user_id):
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + TTL}, SECRET, algorithm="HS256")


def current_user(authorization: str | None = Header(None),
                 session: str | None = Cookie(None, alias=COOKIE)):
    token = session or (authorization or "").removeprefix("Bearer ")
    if not token:
        raise HTTPException(401, "not logged in")
    try:
        return jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired session") from None
