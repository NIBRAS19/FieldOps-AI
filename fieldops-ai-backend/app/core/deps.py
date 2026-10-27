from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models as m
from app.db.session import get_session
from app.security import tokens
from app.security.rbac import Perm, has
from app.services import audit

bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), session: Session = Depends(get_session)) -> m.User:
    if creds is None:
        raise AppError("UNAUTHENTICATED", "Authentication required.", 401)
    claims = tokens.decode(creds.credentials)
    # Role is ALWAYS loaded from the database, never trusted from the token, so role changes apply immediately.
    user = session.scalar(select(m.User).where(m.User.id == claims["sub"], m.User.workspace_id == claims["ws"], m.User.active.is_(True)))
    if not user:
        raise AppError("UNAUTHENTICATED", "Invalid or expired token.", 401)
    return user


def require(*perms: Perm):
    def dep(user: m.User = Depends(current_user), session: Session = Depends(get_session)) -> m.User:
        missing = [p for p in perms if not has(user.role, p)]
        if missing:
            audit.record(session, user.workspace_id, "permission_denied", "permission", ",".join(missing), user=user, result="denied")
            session.commit()
            raise AppError("FORBIDDEN", "Your role does not permit this operation.", 403)
        return user

    return dep
