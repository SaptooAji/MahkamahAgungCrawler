from database.session import engine

from sqlalchemy import text


TABLES = [
    "scraping_runs",
    "discovery_page_jobs",
    "putusan",
]


with engine.connect() as conn:
    for table in TABLES:
        count = conn.execute(
            text(f"SELECT COUNT(*) FROM {table}")
        ).scalar_one()

        print(f"{table}: {count}")