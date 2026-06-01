from flask import Blueprint, request, current_app
import boto3
from botocore.exceptions import ClientError

from app import db
from app.models import User, EC2Instance
from app.utils import success, error, admin_required

ec2_bp = Blueprint("ec2", __name__)


def _client():
    return boto3.client(
        "ec2",
        region_name=current_app.config["AWS_REGION"],
        # aws_access_key_id=current_app.config.get("AWS_ACCESS_KEY_ID"),
        # aws_secret_access_key=current_app.config.get("AWS_SECRET_ACCESS_KEY"),
    )


def _sync_states(instances):
    if not instances:
        return
    try:
        ids = [i.instance_id for i in instances]
        resp = _client().describe_instances(InstanceIds=ids)
        state_map, ip_map = {}, {}
        for reservation in resp["Reservations"]:
            for inst in reservation["Instances"]:
                iid = inst["InstanceId"]
                state_map[iid] = inst["State"]["Name"]
                ip_map[iid]    = inst.get("PublicIpAddress")
        for inst in instances:
            if inst.instance_id in state_map:
                inst.state     = state_map[inst.instance_id]
                inst.public_ip = ip_map.get(inst.instance_id)
        db.session.commit()
    except Exception:
        pass


@ec2_bp.route("", methods=["GET"])
@admin_required
def list_instances():
    instances = EC2Instance.query.all()
    _sync_states(instances)
    return success([i.to_dict() for i in instances])


@ec2_bp.route("", methods=["POST"])
@admin_required
def create_instance():
    body          = request.get_json(silent=True) or {}
    user_id       = body.get("user_id") or None
    instance_type = body.get("instance_type") or current_app.config.get("EC2_INSTANCE_TYPE", "t3.micro")

    if user_id and not db.session.get(User, int(user_id)):
        return error("사용자를 찾을 수 없습니다.", 404)

    ami_id = current_app.config.get("EC2_AMI_ID")
    if not ami_id:
        return error("EC2_AMI_ID가 설정되지 않았습니다.", 500)

    params = {
        "ImageId":      ami_id,
        "InstanceType": instance_type,
        "MinCount":     1,
        "MaxCount":     1,
    }
    if current_app.config.get("EC2_KEY_NAME"):
        params["KeyName"] = current_app.config["EC2_KEY_NAME"]
    if current_app.config.get("EC2_SECURITY_GROUP_ID"):
        params["SecurityGroupIds"] = [current_app.config["EC2_SECURITY_GROUP_ID"]]
    if current_app.config.get("EC2_SUBNET_ID"):
        params["SubnetId"] = current_app.config["EC2_SUBNET_ID"]

    try:
        resp         = _client().run_instances(**params)
        aws_inst     = resp["Instances"][0]
        record       = EC2Instance(
            instance_id=aws_inst["InstanceId"],
            instance_type=instance_type,
            state=aws_inst["State"]["Name"],
            user_id=user_id,
        )
        db.session.add(record)
        db.session.commit()
        return success(record.to_dict(), "인스턴스가 생성되었습니다.", 201)
    except ClientError as e:
        return error(e.response["Error"]["Message"], 500)
    except Exception as e:
        return error(str(e), 500)


@ec2_bp.route("/<int:record_id>", methods=["DELETE"])
@admin_required
def terminate_instance(record_id):
    record = db.session.get(EC2Instance, record_id)
    if not record:
        return error("인스턴스를 찾을 수 없습니다.", 404)

    try:
        _client().terminate_instances(InstanceIds=[record.instance_id])
        db.session.delete(record)
        db.session.commit()
        return success(message="인스턴스가 삭제되었습니다.")
    except ClientError as e:
        return error(e.response["Error"]["Message"], 500)
    except Exception as e:
        return error(str(e), 500)
