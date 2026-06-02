from datetime import datetime, timezone

from flask import Blueprint, request, current_app

import requests as http
from requests.exceptions import ConnectionError, Timeout

from app import db
from app.models import EC2Instance, LoadLog
from app.utils import success, error, admin_required

load_bp = Blueprint("load", __name__)


def _agent_url(private_ip: str, path: str, port: int) -> str:
    return f"http://{private_ip}:{port}{path}"


def _log_payload(record_id: int) -> dict:
    """에이전트에 전달할 로그 관련 필드. BACKEND_INTERNAL_URL 미설정 시 빈 dict."""
    backend_url = current_app.config.get("BACKEND_INTERNAL_URL", "").rstrip("/")
    if not backend_url:
        return {}
    return {
        "_log_url":   f"{backend_url}/api/load/{record_id}/logs",
        "_log_token": current_app.config.get("INTERNAL_AGENT_TOKEN", ""),
    }


# ---------------------------------------------------------------------------
# 이벤트 로그 수신 (load.py → 백엔드, 1초마다)
# ---------------------------------------------------------------------------

@load_bp.route("/<int:record_id>/logs", methods=["POST"])
def ingest_logs(record_id):
    body  = request.get_json(silent=True) or {}
    token = current_app.config.get("INTERNAL_AGENT_TOKEN", "")

    if token and body.get("token") != token:
        return error("Unauthorized", 401)

    events = body.get("events", [])
    if not events:
        return success(message="0개 저장됨")

    records = []
    for ev in events:
        try:
            occurred_at = datetime.fromtimestamp(ev["t"], tz=timezone.utc).replace(tzinfo=None)
            records.append(LoadLog(
                ec2_instance_id=record_id,
                occurred_at=occurred_at,
                status_code=ev.get("s"),
                latency_ms=float(ev.get("l", 0)),
                error=str(ev["e"])[:120] if ev.get("e") else None,
            ))
        except Exception:
            continue

    db.session.add_all(records)
    db.session.commit()
    return success(message=f"{len(records)}개 저장됨")


# ---------------------------------------------------------------------------
# 단일 인스턴스 실행
# ---------------------------------------------------------------------------

@load_bp.route("/<int:record_id>/run", methods=["POST"])
@admin_required
def run(record_id):
    inst = db.session.get(EC2Instance, record_id)
    if not inst:
        return error("인스턴스를 찾을 수 없습니다.", 404)
    if not inst.private_ip:
        return error("Private IP가 없습니다. 인스턴스가 실행 중인지 확인하세요.", 503)
    if not inst.user:
        return error("인스턴스에 배정된 사용자가 없습니다.", 400)
    if not inst.user.endpoint:
        return error("사용자의 Endpoint가 설정되지 않았습니다.", 400)

    port = current_app.config.get("AGENT_PORT", 7000)
    body = request.get_json(silent=True) or {}
    body.update({"url": inst.user.endpoint, **_log_payload(record_id)})

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


# ---------------------------------------------------------------------------
# 다중 인스턴스 실행
# ---------------------------------------------------------------------------

@load_bp.route("/run-multi", methods=["POST"])
@admin_required
def run_multi():
    body       = request.get_json(silent=True) or {}
    record_ids = body.pop("record_ids", [])

    if not record_ids:
        return error("인스턴스를 하나 이상 선택해주세요.", 400)

    port = current_app.config.get("AGENT_PORT", 7000)
    started, failed = [], []

    for record_id in record_ids:
        inst = db.session.get(EC2Instance, record_id)

        def _fail(reason, inst=inst, record_id=record_id):
            failed.append({
                "id":          record_id,
                "instance_id": inst.instance_id if inst else None,
                "username":    inst.user.username if inst and inst.user else None,
                "reason":      reason,
            })

        if not inst:
            _fail("인스턴스를 찾을 수 없습니다.")
            continue
        if not inst.private_ip:
            _fail("Private IP가 없습니다.")
            continue
        if not inst.user:
            _fail("배정된 사용자가 없습니다.")
            continue
        if not inst.user.endpoint:
            _fail("사용자의 Endpoint가 설정되지 않았습니다.")
            continue

        payload = {**body, "url": inst.user.endpoint, **_log_payload(record_id)}
        try:
            resp = http.post(_agent_url(inst.private_ip, "/run", port), json=payload, timeout=5)
            data = resp.json()
            if resp.status_code == 409:
                _fail(data.get("message", "이미 실행 중입니다."))
            else:
                started.append({
                    "id":          record_id,
                    "instance_id": inst.instance_id,
                    "username":    inst.user.username,
                })
        except Timeout:
            _fail("에이전트 연결 타임아웃")
        except ConnectionError:
            _fail("에이전트에 연결할 수 없습니다.")
        except Exception as e:
            _fail(str(e))

    return success(
        {"started": started, "failed": failed},
        f"{len(started)}개 시작, {len(failed)}개 실패",
    )


# ---------------------------------------------------------------------------
# 상태 조회
# ---------------------------------------------------------------------------

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
