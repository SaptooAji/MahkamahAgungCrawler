from __future__ import annotations

import argparse

from celery_app.tasks import process_scraping_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue one scraping run into Celery.")
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    result = process_scraping_run.delay(args.run_id)
    print(f"Celery task_id={result.id}")
    print(f"run_id={args.run_id}")


if __name__ == "__main__":
    main()
