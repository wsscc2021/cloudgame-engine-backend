import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    DEBUG = os.getenv("FLASK_ENV") == "development"

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{os.getenv('DB_USER', 'root')}:"
        f"{os.getenv('DB_PASSWORD', '')}@"
        f"{os.getenv('DB_HOST', 'localhost')}:"
        f"{os.getenv('DB_PORT', '3306')}/"
        f"{os.getenv('DB_NAME', 'cloudgame')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        seconds=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))
    )

    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin1234!")

    # AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID")
    # AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION            = os.getenv("AWS_REGION", "ap-northeast-2")
    EC2_AMI_ID            = os.getenv("EC2_AMI_ID")
    EC2_INSTANCE_TYPE     = os.getenv("EC2_INSTANCE_TYPE", "t3.micro")
    EC2_KEY_NAME          = os.getenv("EC2_KEY_NAME")
    EC2_SECURITY_GROUP_ID = os.getenv("EC2_SECURITY_GROUP_ID")
    EC2_SUBNET_ID         = os.getenv("EC2_SUBNET_ID")

    AGENT_PORT            = int(os.getenv("AGENT_PORT", 7000))
    LOADCLIENT_DIR        = os.getenv("LOADCLIENT_DIR", "")
    BACKEND_INTERNAL_URL  = os.getenv("BACKEND_INTERNAL_URL", "")
    INTERNAL_AGENT_TOKEN  = os.getenv("INTERNAL_AGENT_TOKEN", "")

    LOG_DIR   = os.getenv("LOG_DIR",   "/var/log/cloudgame/backend")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
