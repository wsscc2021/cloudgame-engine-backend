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


# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------

def _save_events(record_id: int, events: list) -> int:
    """events 리스트를 DB에 저장하고 저장된 건수를 반환."""
    if not events:
        return 0
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
    try:
        db.session.add_all(records)
        db.session.commit()
        return len(records)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("이벤트 로그 저장 실패 (record_id=%s): %s", record_id, exc)
        return 0


# ---------------------------------------------------------------------------
# 이벤트 로그 조회
# ---------------------------------------------------------------------------

@load_bp.route("/<int:record_id>/logs", methods=["GET"])
@admin_required
def get_logs(record_id):
    limit  = min(int(request.args.get("limit", 200)), 1000)
    offset = int(request.args.get("offset", 0))

    rows = (
        LoadLog.query
        .filter_by(ec2_instance_id=record_id)
        .order_by(LoadLog.occurred_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    total = LoadLog.query.filter_by(ec2_instance_id=record_id).count()

    return success({
        "total": total,
        "logs": [
            {
                "id":          r.id,
                "occurred_at": r.occurred_at.isoformat(),
                "status_code": r.status_code,
                "latency_ms":  r.latency_ms,
                "error":       r.error,
            }
            for r in rows
        ],
    })


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
    body["url"] = inst.user.endpoint

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

        payload = {**body, "url": inst.user.endpoint}
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
    except Timeout:
        return error("에이전트 연결 타임아웃", 504)
    except ConnectionError:
        return error("에이전트에 연결할 수 없습니다. 인스턴스가 실행 중인지 확인하세요.", 503)
    except Exception as e:
        return error(str(e), 503)

    # 에이전트 이벤트 버퍼를 드레인해 DB에 저장
    try:
        ev_resp = http.get(_agent_url(inst.private_ip, "/events", port), timeout=5)
        _save_events(record_id, ev_resp.json().get("events", []))
    except Exception:
        pass

    return success(resp.json())
