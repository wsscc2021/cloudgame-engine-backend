from flask import Blueprint, request
from flask_jwt_extended import create_access_token

from app.models import User
from app.utils import success, error

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return error("username과 password를 입력해주세요.", 400)

    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(password):
        return error("인증 정보가 올바르지 않습니다.", 401)

    token = create_access_token(identity=str(user.id))
    return success({"access_token": token, "user": user.to_dict()}, "로그인 성공")
