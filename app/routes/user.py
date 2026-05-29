from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import db
from app.models import User
from app.utils import success, error, admin_required

user_bp = Blueprint("user", __name__)


@user_bp.route("", methods=["POST"])
@admin_required
def create_user():
    body = request.get_json(silent=True) or {}
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        return error("username, password는 필수입니다.", 400)

    if User.query.filter_by(username=username).first():
        return error("이미 사용 중인 username입니다.", 409)

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return success(user.to_dict(), "사용자가 생성되었습니다.", 201)


@user_bp.route("", methods=["GET"])
@jwt_required()
def get_users():
    users = User.query.all()
    return success([u.to_dict() for u in users])


@user_bp.route("/<int:user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return error("사용자를 찾을 수 없습니다.", 404)
    return success(user.to_dict())


@user_bp.route("/<int:user_id>", methods=["PUT"])
@admin_required
def update_user(user_id):
    if int(get_jwt_identity()) == user_id:
        return error("자기 자신은 수정할 수 없습니다.", 403)

    user = db.session.get(User, user_id)
    if not user:
        return error("사용자를 찾을 수 없습니다.", 404)

    body = request.get_json(silent=True) or {}

    new_username = body.get("username", "").strip()
    new_password = body.get("password", "")
    new_role = body.get("role", "").strip()

    if new_username and new_username != user.username:
        if User.query.filter_by(username=new_username).first():
            return error("이미 사용 중인 username입니다.", 409)
        user.username = new_username

    if new_password:
        user.set_password(new_password)

    if new_role in ("admin", "user"):
        user.role = new_role

    db.session.commit()
    return success(user.to_dict(), "사용자 정보가 수정되었습니다.")


@user_bp.route("/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    current_user_id = int(get_jwt_identity())
    if current_user_id == user_id:
        return error("자기 자신은 삭제할 수 없습니다.", 403)

    user = db.session.get(User, user_id)
    if not user:
        return error("사용자를 찾을 수 없습니다.", 404)

    if user.username == "administrator":
        return error("administrator 계정은 삭제할 수 없습니다.", 403)

    db.session.delete(user)
    db.session.commit()
    return success(message="사용자가 삭제되었습니다.")
