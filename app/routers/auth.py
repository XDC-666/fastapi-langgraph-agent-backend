"""认证路由：注册 / 登录 / 获取当前用户。"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import UserCreate, UserOut
from app.services.auth_service import authenticate_user, issue_token, register_user
from app.utils.lockout import clear_lock, is_locked, record_failure
from app.utils.rate_limit import login_rate_limit

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    """用户注册。"""
    try:
        return register_user(db, payload.username, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/login", dependencies=[Depends(login_rate_limit)])
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """用户登录，返回 JWT（OAuth2 密码流，兼容 Swagger Authorize）。

    两层防护：按 IP 限流 + 按账号失败锁定，Redis 不可用时均降级放行。
    """
    identifier = form_data.username

    # 锁定中的账号直接拒绝，不再查数据库
    locked_ttl = await is_locked(identifier)
    if locked_ttl is not None:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"账号已锁定，请 {locked_ttl} 秒后重试",
        )

    user = await run_in_threadpool(authenticate_user, db, identifier, form_data.password)
    if user is None:
        ip = request.client.host if request.client else "unknown"
        await record_failure(identifier, ip)
        # 统一错误信息，避免暴露「用户是否存在」
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await clear_lock(identifier)
    return {"access_token": issue_token(user), "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return current_user
