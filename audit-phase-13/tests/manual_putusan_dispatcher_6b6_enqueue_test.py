from __future__ import annotations

import os
from unittest.mock import patch

from celery.result import AsyncResult

from celery_app import tasks


FAKE_IDS = [901, 902, 903, 904, 905]
FAKE_TASK_IDS = [
    "fake-task-901",
    "fake-task-902",
    "fake-task-903",
    "fake-task-904",
    "fake-task-905",
]


class FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


def main() -> None:
    print("=" * 70)
    print("PHASE 6B.6 - PUTUSAN CELERY ENQUEUE")
    print("=" * 70)
    print("ENV_FILE:", os.getenv("ENV_FILE", ".env"))

    calls: list[int] = []
    task_counter = iter(FAKE_TASK_IDS)

    def fake_delay(putusan_id: int) -> FakeAsyncResult:
        calls.append(putusan_id)
        return FakeAsyncResult(next(task_counter))

    with patch.object(
        tasks,
        "get_pending_putusan_ids",
        return_value=list(FAKE_IDS),
    ) as mocked_selector, patch.object(
        tasks.process_putusan,
        "delay",
        side_effect=fake_delay,
    ) as mocked_delay:
        result = tasks.dispatch_pending_putusan(batch_size=5)

    print("Dispatcher result:")
    print("  dispatched:", result["dispatched"])
    print("  putusan_ids:", result["putusan_ids"])
    print("  task_ids:", result["task_ids"])

    # 6B.6.1: selector receives requested batch size.
    mocked_selector.assert_called_once_with(batch_size=5)
    print("PASS: selector dipanggil dengan batch_size=5")

    # 6B.6.2: every selected ID is enqueued exactly once.
    assert calls == FAKE_IDS, (
        f"Urutan enqueue salah. expected={FAKE_IDS}, actual={calls}"
    )
    assert mocked_delay.call_count == len(FAKE_IDS)
    print("PASS: setiap Putusan di-enqueue tepat satu kali")

    # 6B.6.3: returned metadata matches enqueue results.
    assert result["dispatched"] == len(FAKE_IDS)
    assert result["putusan_ids"] == FAKE_IDS
    assert result["task_ids"] == FAKE_TASK_IDS
    print("PASS: metadata dispatched/putusan_ids/task_ids konsisten")

    # 6B.6.4: this test intentionally mocks .delay(), therefore no real
    # Celery message is sent and no Putusan claim can happen here.
    print("PASS: tidak mengirim task Celery nyata / tidak membuka browser")

    # 6B.6.5: hard limit remains enforced by production dispatcher.
    try:
        tasks.dispatch_pending_putusan(batch_size=6)
    except ValueError as exc:
        assert "maksimal 5" in str(exc)
        print("PASS: batch_size > 5 ditolak")
    else:
        raise AssertionError("Dispatcher menerima batch_size > 5")

    print("\n" + "=" * 70)
    print("PHASE 6B.6: PASS")
    print("=" * 70)


if __name__ == "__main__":
    main()
