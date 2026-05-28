from functools import wraps
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from app import db
from app.utils.response import error


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        from app.models import User
        user = db.session.get(User, int(get_jwt_identity()))
        if not user or not user.is_admin:
            return error("관리자만 접근할 수 있습니다.", 403)
        return fn(*args, **kwargs)
    return wrapper
