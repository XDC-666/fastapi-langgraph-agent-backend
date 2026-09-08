"""安全工具：密码哈希、JWT 生成与解析。

- 密码使用 bcrypt 哈希，杜绝明文存储。
- JWT 用于无状态登录认证。

说明：早期版本使用 passlib 做哈希，但 passlib 已停止维护且与 bcrypt>=4.1 不兼容
（加载后端时报 `module 'bcrypt' has no attribute '__about__'`，导致注册直接失败）。
这里改为直接调用 bcrypt 官方 API，去掉这层废弃依赖。
"""
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def _prehash(password: str) -> bytes:
    """先把密码做一次 SHA-256 再 base64。

    bcrypt 只处理前 72 字节，超长密码会被静默截断。先哈希成固定 44 字节，
    既规避长度限制，也避免长密码在截断后强度下降。
    """
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    """对明文密码进行哈希。"""
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(_prehash(plain_password), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str | int, expires_delta: Optional[timedelta] = None) -> str:
    """生成 JWT 访问令牌。subject 通常放用户 id。"""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {"sub": str(subject), "exp": expire}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """解析 JWT，返回 subject（用户 id 字符串）；失败返回 None。"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
