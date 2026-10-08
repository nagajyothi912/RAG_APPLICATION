from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.auth import AuthUser, Role, authenticate, current_user, issue_token

router = APIRouter(tags=["auth"], prefix="/auth")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    # The role the login screen was on. Optional so a script can just sign in;
    # when given, it must match the account, so picking "Admin" with the
    # chatbot account fails instead of quietly landing in the chatbot.
    role: Optional[Role] = None


class UserInfo(BaseModel):
    username: str
    role: Role


class LoginResponse(BaseModel):
    token: str
    expires_at: int
    user: UserInfo


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    user = authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    if payload.role and payload.role != user.role:
        raise HTTPException(
            status_code=403,
            detail=f"This account signs in as {user.role}, not {payload.role}.",
        )
    token, expires_at = issue_token(user)
    return LoginResponse(
        token=token,
        expires_at=expires_at,
        user=UserInfo(username=user.username, role=user.role),
    )


@router.get("/me", response_model=UserInfo)
def me(user: AuthUser = Depends(current_user)) -> UserInfo:
    return UserInfo(username=user.username, role=user.role)
