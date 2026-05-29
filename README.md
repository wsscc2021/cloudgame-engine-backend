
## Install on Amazon linux 2023

- Install Packages
```
sudo dnf update -y

# Nginx, Python, Git
sudo dnf install -y nginx python3.12 python3.12-pip git
```

- deploy code
```
sudo mkdir -p /srv/cloudgame-engine/backend
sudo chown -R ec2-user:ec2-user /srv/cloudgame-engine

# 프로젝트 복사 (또는 git clone)
git clone https://github.com/wsscc2021/cloudgame-engine-backend.git /srv/cloudgame-engine/backend
```

- application setup
```
cd /srv/cloudgame-engine/backend

# 가상환경 생성 및 패키지 설치
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 환경변수 파일 생성
cp .env.example .env
vi .env   # DB 접속 정보, JWT_SECRET_KEY, ADMIN_PASSWORD 수정
```

```
sudo tee /etc/systemd/system/cloudgame-backend.service > /dev/null <<EOF
[Unit]
Description=CloudGame Backend (Gunicorn)
After=network.target mysqld.service

[Service]
User=ec2-user
WorkingDirectory=/srv/cloudgame-engine/backend
EnvironmentFile=/srv/cloudgame-engine/backend/.env
ExecStart=/srv/cloudgame-engine/backend/venv/bin/gunicorn \
    --workers 4 \
    --bind 127.0.0.1:5000 \
    run:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now cloudgame-backend
```

```
sudo systemctl status cloudgame-backend
curl -X POST http://127.0.0.1:5000/api/auth/login   # {"success": false, ...} 응답이면 OK
```

- nginx setup

```
sudo tee /etc/nginx/conf.d/cloudgame.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    root /srv/cloudgame-engine/frontend/dist;
    index index.html;

    # Vue Router — 새로고침 시 index.html 반환
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Flask API 프록시
    location /api/ {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    }
}
EOF

sudo nginx -t          # 설정 문법 검사
sudo systemctl enable --now nginx
```
