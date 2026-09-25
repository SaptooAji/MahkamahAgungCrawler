# workers/celery_app.py
from celery import Celery
import os

# Redis bertindak sebagai perantara pesan (Broker)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "ma_crawler",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["workers.tasks"]
)