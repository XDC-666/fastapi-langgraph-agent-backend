"""全局依赖：当前登录用户解析、数据库会话等。"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.utils.security import decode_access_token

# tokenUrl 指向登录接口，供 Swagger "Authorize" 按钮使用
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer Token，返回当前登录用户。失败抛出 401。"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或过期的凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id = decode_access_token(token)
    if user_id is None:
        raise credentials_exception
    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        raise credentials_exception from None
    if parsed_user_id <= 0:
        raise credentials_exception
    user = db.get(User, parsed_user_id)
    if user is None:
        raise credentials_exception
    return user
