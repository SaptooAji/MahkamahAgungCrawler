import os

from celery import Celery
from dotenv import load_dotenv


load_dotenv()


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")


REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"


celery_app = Celery(
    "mahkamah_agung_crawler",
    broker=REDIS_URL,
    backend=REDIS_URL,
)


celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Jakarta",
    enable_utc=True,
)