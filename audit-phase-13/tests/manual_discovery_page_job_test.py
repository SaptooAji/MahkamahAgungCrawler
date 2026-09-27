from database.session import SessionLocal
from repositories.discovery_page_job_repository import claim_page_jobs


def main():
    session = SessionLocal()

    try:
        page_jobs = claim_page_jobs(
            session,
            worker_id="test-worker-1",
            batch_size=1,
        )

        session.commit()

        print("CLAIMED PAGE JOBS:")

        for page_job in page_jobs:
            print(
                page_job.id,
                page_job.page_number,
                page_job.status,
                page_job.processing_worker_id,
                page_job.processing_token,
            )

    finally:
        session.close()


if __name__ == "__main__":
    main()