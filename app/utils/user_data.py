"""Generates EC2 user data that installs and starts the load agent."""
import base64
import gzip
import os


def _loadclient_dir() -> str:
    configured = os.environ.get("LOADCLIENT_DIR", "")
    if configured and os.path.isdir(configured):
        return configured
    # backend/app/utils/ -> backend/app/ -> backend/
    here        = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(os.path.dirname(here))
    candidate   = os.path.join(backend_dir, "loadagent")
    if os.path.isdir(candidate):
        return candidate
    raise RuntimeError(
        "backend/loadagent 디렉터리를 찾을 수 없습니다. "
        "LOADCLIENT_DIR 환경변수를 설정하거나 backend/loadagent/ 디렉터리가 있는지 확인하세요."
    )


def _b64gz(filename: str) -> str:
    path = os.path.join(_loadclient_dir(), filename)
    with open(path, "rb") as f:
        return base64.b64encode(gzip.compress(f.read())).decode()


def generate(agent_port: int = 7000) -> str:
    load_b64  = _b64gz("load.py")
    agent_b64 = _b64gz("agent.py")

    # printf 로 systemd service 파일 작성 (heredoc 이스케이프 문제 방지)
    svc = (
        "[Unit]\\n"
        "Description=Load Agent HTTP Server\\n"
        "After=network.target\\n\\n"
        "[Service]\\n"
        f"ExecStart=/usr/bin/python3 /loadagent/agent.py\\n"
        f"Environment=AGENT_PORT={agent_port}\\n"
        "Restart=always\\n"
        "RestartSec=5\\n\\n"
        "[Install]\\n"
        "WantedBy=multi-user.target\\n"
    )

    return (
        "#!/bin/bash\n"
        "set -e\n\n"
        "# 기본 패키지 설치\n"
        "dnf install -y python3 python3-pip\n\n"
        "# 에이전트 디렉터리 생성\n"
        "mkdir -p /loadagent\n\n"
        "# 스크립트 배포\n"
        f"echo '{load_b64}'  | base64 -d | gunzip > /loadagent/load.py\n"
        f"echo '{agent_b64}' | base64 -d | gunzip > /loadagent/agent.py\n"
        "chmod +x /loadagent/load.py /loadagent/agent.py\n\n"
        "# Python 의존성 설치\n"
        "pip3 install --quiet aiohttp flask\n\n"
        "# systemd 서비스 등록\n"
        f"printf '{svc}' > /etc/systemd/system/loadagent.service\n\n"
        "systemctl daemon-reload\n"
        "systemctl enable --now loadagent\n"
    )
