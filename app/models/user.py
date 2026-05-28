from datetime import datetime, timezone
import bcrypt
from app import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def set_password(self, plain_password: str) -> None:
        self.password_hash = bcrypt.hashpw(
            plain_password.encode(), bcrypt.gensalt()
        ).decode()

    def check_password(self, plain_password: str) -> bool:
        return bcrypt.checkpw(plain_password.encode(), self.password_hash.encode())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
