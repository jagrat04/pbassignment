"""Authentication and role enforcement.

Two roles, actually enforced at the dependency layer rather than declared in a
docstring:

    editor  -> may read and write shows/seasons/episodes/artwork
    admin   -> everything an editor may do, plus publish and rollback

`require_admin` is the only gate on the publish endpoints, and it is a
dependency, so there is no route that can forget to call it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

ROLES = ("editor", "admin")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    unauth = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in to continue.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise unauth
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session expired. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.PyJWTError:
        raise unauth from None

    # The role is re-read from the database on every request. A token minted
    # while someone was an admin stops granting publish the moment their role
    # is changed, without waiting for the token to expire.
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise unauth
    return user


def require_editor(user: User = Depends(get_current_user)) -> User:
    """Any signed-in content user. Both roles pass."""
    if user.role not in ROLES:
        raise HTTPException(status_code=403, detail="Your account has no content role.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Publishing and rollback only."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Publishing is limited to admins. Ask an admin to run the publish, "
                "or ask your team lead to change your role."
            ),
        )
    return user
