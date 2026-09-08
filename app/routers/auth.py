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
        user = register_user(db, payload.username, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return user


@router.post("/login", dependencies=[Depends(login_rate_limit)])
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """用户登录，返回 JWT。

    使用 OAuth2PasswordRequestForm（username/password），
    便于 Swagger 自带的 Authorize 按钮直接调用。

    已叠加两层防护：
    1. 按 IP 的登录限流（防高频爆破）；
    2. 按账号的失败锁定（连续失败达上限后锁定一段时间，防暴力破解）。
    两者在 Redis 不可用时均降级放行，不会拖垮登录主流程。
    """
    identifier = form_data.username

    # 先查是否已被锁定（锁定中直接拒绝，不再打数据库）
    locked_ttl = await is_locked(identifier)
    if locked_ttl is not None:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"账号已锁定，请 {locked_ttl} 秒后重试",
        )

    # 同步 ORM 放到线程池，避免阻塞事件循环
    user = await run_in_threadpool(authenticate_user, db, identifier, form_data.password)
    if user is None:
        ip = request.client.host if request.client else "unknown"
        await record_failure(identifier, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 登录成功：清除失败计数与锁定
    await clear_lock(identifier)
    return {"access_token": issue_token(user), "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return current_user
