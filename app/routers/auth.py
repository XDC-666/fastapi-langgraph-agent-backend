"""认证路由：注册 / 登录 / 获取当前用户。"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import UserCreate, UserOut
from app.services.auth_service import authenticate_user, issue_token, register_user
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
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """用户登录，返回 JWT。

    使用 OAuth2PasswordRequestForm（username/password），
    便于 Swagger 自带的 Authorize 按钮直接调用。

    已加按 IP 的登录限流，防止密码暴力破解。
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": issue_token(user), "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return current_user
