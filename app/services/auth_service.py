"""认证相关业务逻辑。"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.user import User
from app.utils.security import (
    create_access_token,
    hash_password,
    verify_password,
)


def register_user(db: Session, username: str, email: str, password: str) -> User:
    """注册新用户；用户名或邮箱重复时抛 ValueError。"""
    exists = (
        db.query(User)
        .filter(or_(User.username == username, User.email == email))
        .first()
    )
    if exists is not None:
        raise ValueError("用户名或邮箱已存在")

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, identifier: str, password: str) -> User | None:
    """校验用户名或邮箱 + 密码；成功返回 User，失败返回 None。"""
    user = (
        db.query(User)
        .filter(or_(User.username == identifier, User.email == identifier))
        .first()
    )
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def issue_token(user: User) -> str:
    """为用户签发 JWT。"""
    return create_access_token(user.id)
