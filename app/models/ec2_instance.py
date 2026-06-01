from datetime import datetime, timezone
from app import db


class EC2Instance(db.Model):
    __tablename__ = "ec2_instances"

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    instance_id   = db.Column(db.String(30), unique=True, nullable=False)
    instance_type = db.Column(db.String(20), nullable=False)
    state         = db.Column(db.String(20), nullable=False, default="pending")
    public_ip     = db.Column(db.String(50), nullable=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref="ec2_instances")

    def to_dict(self):
        return {
            "id":            self.id,
            "instance_id":   self.instance_id,
            "instance_type": self.instance_type,
            "state":         self.state,
            "public_ip":     self.public_ip,
            "user_id":       self.user_id,
            "username":      self.user.username if self.user else None,
            "created_at":    self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
