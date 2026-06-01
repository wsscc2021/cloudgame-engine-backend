from flask import Blueprint, request, current_app

import requests as http
from requests.exceptions import ConnectionError, Timeout

from app import db
from app.models import EC2Instance
from app.utils import success, error, admin_required

load_bp = Blueprint("load", __name__)


def _agent_url(public_ip: str, path: str, port: int) -> str:
    return f"http://{public_ip}:{port}{path}"


@load_bp.route("/<int:record_id>/run", methods=["POST"])
@admin_required
def run(record_id):
    inst = db.session.get(EC2Instance, record_id)
    if not inst:
        return error("인스턴스를 찾을 수 없습니다.", 404)
    if not inst.private_ip:
        return error("Private IP가 없습니다. 인스턴스가 실행 중인지 확인하세요.", 503)

    port = current_app.config.get("AGENT_PORT", 7000)
    body = request.get_json(silent=True) or {}
    try:
        resp = http.post(_agent_url(inst.private_ip, "/run", port), json=body, timeout=5)
        data = resp.json()
        if resp.status_code == 409:
            return error(data.get("message", "이미 실행 중입니다."), 409)
        return success(message=data.get("message", "테스트가 시작되었습니다."))
    except Timeout:
        return error("에이전트 연결 타임아웃", 504)
    except ConnectionError:
        return error("에이전트에 연결할 수 없습니다. 인스턴스가 실행 중인지 확인하세요.", 503)
    except Exception as e:
        return error(str(e), 503)


@load_bp.route("/<int:record_id>/status", methods=["GET"])
@admin_required
def status(record_id):
    inst = db.session.get(EC2Instance, record_id)
    if not inst:
        return error("인스턴스를 찾을 수 없습니다.", 404)
    if not inst.private_ip:
        return error("Private IP가 없습니다.", 503)

    port = current_app.config.get("AGENT_PORT", 7000)
    try:
        resp = http.get(_agent_url(inst.private_ip, "/status", port), timeout=5)
        return success(resp.json())
    except Timeout:
        return error("에이전트 연결 타임아웃", 504)
    except ConnectionError:
        return error("에이전트에 연결할 수 없습니다. 인스턴스가 실행 중인지 확인하세요.", 503)
    except Exception as e:
        return error(str(e), 503)
