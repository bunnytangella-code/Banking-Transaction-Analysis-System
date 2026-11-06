import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+mysqlconnector://"
        f"{quote_plus(os.getenv('DB_USER', 'root'))}:"
        f"{quote_plus(os.getenv('DB_PASSWORD', 'root'))}@"
        f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '3306')}/"
        f"{quote_plus(os.getenv('DB_NAME', 'banksight_db'))}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    PROPAGATE_EXCEPTIONS = False
    UNUSUAL_AMOUNT_THRESHOLD = os.getenv("UNUSUAL_AMOUNT_THRESHOLD", "50000")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("FLASK_DEBUG", "true").lower() != "true"
