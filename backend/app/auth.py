"""Demo auth: log in as any Steam user id from the dataset, get a JWT."""
import os
import time

import jwt
from fastapi import Header, HTTPException

SECRET = os.environ.get("JWT_SECRET", "dev-only-secret")


def issue(user_id):
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + 86400}, SECRET, algorithm="HS256")


def current_user(authorization: str = Header(...)):
    try:
        return jwt.decode(authorization.removeprefix("Bearer "), SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token") from None
