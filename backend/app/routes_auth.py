from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr

from .db import get_db
from .deps import audit, current_user
from .security import (create_access_token, create_refresh_token, set_auth_cookies,
                       verify_password)

router = APIRouter(prefix="/auth", tags=["auth"])
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    db = get_db()
    email = payload.email.lower()
    fwd = request.headers.get("X-Forwarded-For", "")
    ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))
    now = datetime.now(timezone.utc)

    # Two keys: per-email (survives multi-proxy ingress) and per-ip+email.
    identifiers = [f"email:{email}", f"{ip}:{email}"]
    locked = await db.login_attempts.find_one(
        {"identifier": {"$in": identifiers}, "locked_until": {"$gt": now.isoformat()}})
    if locked:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        count = 0
        for identifier in identifiers:
            attempt = await db.login_attempts.find_one({"identifier": identifier})
            count = (attempt.get("count", 0) if attempt else 0) + 1
            values = {"identifier": identifier, "count": count, "updated_at": now.isoformat()}
            if count >= MAX_ATTEMPTS:
                values["locked_until"] = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            await db.login_attempts.update_one({"identifier": identifier}, {"$set": values}, upsert=True)
        await audit.record(actor=email, actor_role="anonymous", action="auth.login_failed",
                           entity_type="user", status=401, metadata={"attempts": count})
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await db.login_attempts.delete_many({"identifier": {"$in": identifiers}})
    uid, role = str(user["_id"]), user.get("role", "viewer")
    access = create_access_token(uid, email, role)
    set_auth_cookies(response, access, create_refresh_token(uid))
    await audit.record(actor=email, actor_role=role, action="auth.login", entity_type="user",
                       entity_id=uid, status=200)
    return {"id": uid, "email": email, "name": user.get("name"), "role": role,
            "access_token": access}


@router.post("/logout")
async def logout(response: Response, user: dict = Depends(current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    await audit.record(actor=user["email"], actor_role=user["role"], action="auth.logout",
                       entity_type="user", entity_id=user["id"], status=200)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    import jwt

    from .security import JWT_ALGORITHM, get_jwt_secret
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = await get_db().users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access = create_access_token(str(user["_id"]), user["email"], user.get("role", "viewer"))
    set_auth_cookies(response, access, create_refresh_token(str(user["_id"])))
    return {"ok": True, "access_token": access}
