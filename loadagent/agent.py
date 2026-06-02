#!/usr/bin/env python3
"""EC2 Load Agent — HTTP wrapper around load.py"""

import json
import os
import subprocess
import threading
import time

from flask import Flask, jsonify, request

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "load.py")
PORT   = int(os.environ.get("AGENT_PORT", 7000))

app = Flask(__name__)
_lock  = threading.Lock()
_state = {
    "running":     False,
    "started_at":  None,
    "finished_at": None,
    "output":      None,
    "error":       None,
}

_event_lock   = threading.Lock()
_event_buffer = []  # load.py 가 1초마다 적재, 백엔드가 /events 로 드레인


def _execute(cmd: list) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        with _lock:
            _state.update({
                "running":     False,
                "finished_at": time.time(),
                "output":      proc.stdout,
                "error":       proc.stderr.strip() or None,
            })
    except subprocess.TimeoutExpired:
        with _lock:
            _state.update({
                "running":     False,
                "finished_at": time.time(),
                "error":       "테스트 타임아웃 (2시간 초과)",
            })
    except Exception as exc:
        with _lock:
            _state.update({
                "running":     False,
                "finished_at": time.time(),
                "error":       str(exc),
            })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"success": True})


@app.route("/ingest", methods=["POST"])
def ingest():
    """load.py → 에이전트: 이벤트 적재 (1초마다)"""
    body   = request.get_json(silent=True) or {}
    events = body.get("events", [])
    if events:
        with _event_lock:
            _event_buffer.extend(events)
    return jsonify({"success": True, "ingested": len(events)})


@app.route("/events", methods=["GET"])
def drain_events():
    """백엔드 → 에이전트: 버퍼 드레인 (상태 조회 시 호출)"""
    with _event_lock:
        events = list(_event_buffer)
        _event_buffer.clear()
    return jsonify({"success": True, "events": events})


@app.route("/run", methods=["POST"])
def run():
    body = request.get_json(silent=True) or {}
    with _lock:
        if _state["running"]:
            return jsonify({"success": False, "message": "이미 실행 중입니다."}), 409
        _state.update({
            "running":     True,
            "started_at":  time.time(),
            "finished_at": None,
            "output":      None,
            "error":       None,
        })

    cmd = [
        "python3", SCRIPT,
        "--url",      str(body.get("url", "http://localhost")),
        "--path",     str(body.get("path", "/")),
        "--method",   str(body.get("method", "GET")),
        "--rps",      str(int(body.get("rps", 10))),
        "--duration", str(int(body.get("duration", 10))),
        "--timeout",  str(float(body.get("timeout", 10))),
    ]
    if body.get("body"):
        raw = body["body"]
        cmd += ["--body", json.dumps(raw) if isinstance(raw, dict) else str(raw)]
    if body.get("query"):
        cmd += ["--query", str(body["query"])]
    for h in body.get("headers", []):
        cmd += ["--header", str(h)]
    # load.py 이벤트를 에이전트 자신의 /ingest 로 전송 (외부 URL 설정 불필요)
    cmd += ["--log-url", f"http://localhost:{PORT}/ingest", "--log-token", ""]

    with _event_lock:
        _event_buffer.clear()  # 이전 테스트의 잔여 이벤트 제거

    threading.Thread(target=_execute, args=(cmd,), daemon=True).start()
    return jsonify({"success": True, "message": "테스트가 시작되었습니다."})


@app.route("/status", methods=["GET"])
def status():
    with _lock:
        snap = dict(_state)
    return jsonify({
        "success":     True,
        "running":     snap["running"],
        "started_at":  snap["started_at"],
        "finished_at": snap["finished_at"],
        "output":      snap["output"],
        "error":       snap["error"],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
