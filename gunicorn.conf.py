import os

_log_dir = os.environ.get("LOG_DIR", "/var/log/cloudgame/backend")

bind         = os.environ.get("GUNICORN_BIND", "0.0.0.0:5000")
workers      = int(os.environ.get("GUNICORN_WORKERS", "2"))
worker_class = "sync"
timeout      = 120

accesslog         = os.path.join(_log_dir, "access.log")
errorlog          = os.path.join(_log_dir, "error.log")
loglevel          = os.environ.get("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'


def on_starting(server):
    os.makedirs(_log_dir, exist_ok=True)
