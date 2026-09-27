import os

from celery import Celery
from celery.signals import setup_logging
from dotenv import load_dotenv

from logging_config import configure_logging


env_file = os.getenv("ENV_FILE", ".env")
load_dotenv(env_file)

configure_logging()


@setup_logging.connect
def configure_celery_logging(*args, **kwargs):
    configure_logging()


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("REDIS_DB", "0")

REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

celery_app = Celery(
    "mahkamah_agung_crawler",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["celery_app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Jakarta",
    enable_utc=True,
)