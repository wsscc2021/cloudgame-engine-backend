from app.routes.auth import auth_bp
from app.routes.user import user_bp
from app.routes.ec2 import ec2_bp

__all__ = ["auth_bp", "user_bp", "ec2_bp"]
