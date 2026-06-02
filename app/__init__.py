import logging
import os
from logging.handlers import WatchedFileHandler

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager

from app.config import Config

db = SQLAlchemy()
jwt = JWTManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    _configure_logging(app)

    db.init_app(app)
    jwt.init_app(app)

    from app.routes import auth_bp, user_bp, ec2_bp, load_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(user_bp, url_prefix="/api/users")
    app.register_blueprint(ec2_bp, url_prefix="/api/ec2")
    app.register_blueprint(load_bp, url_prefix="/api/load")

    with app.app_context():
        db.create_all()
        _seed_admin(app)

    return app


def _configure_logging(app):
    log_dir = app.config.get("LOG_DIR", "/var/log/cloudgame")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        return

    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handler = WatchedFileHandler(os.path.join(log_dir, "app.log"), encoding="utf-8")
    handler.setFormatter(fmt)
    handler.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # werkzeug request logs go to Gunicorn's access.log instead
    logging.getLogger("werkzeug").propagate = False


def _seed_admin(app):
    from app.models import User
    if User.query.filter_by(username="administrator").first():
        return
    admin = User(
        username="administrator",
        role="admin",
    )
    admin.set_password(app.config["ADMIN_PASSWORD"])
    db.session.add(admin)
    db.session.commit()
