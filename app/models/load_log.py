from app import db


class LoadLog(db.Model):
    __tablename__ = "load_logs"

    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ec2_instance_id = db.Column(
        db.Integer,
        db.ForeignKey("ec2_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    occurred_at = db.Column(db.DateTime, nullable=False, index=True)
    status_code = db.Column(db.SmallInteger, nullable=True)
    latency_ms  = db.Column(db.Float, nullable=False)
    error       = db.Column(db.String(120), nullable=True)
