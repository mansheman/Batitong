"""Celery task wrapper for the playbook runner."""

from __future__ import annotations

import logging

from celery import shared_task

from . import runner

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="apps.playbooks.tasks.run_playbook_step", queue="llm")
def run_playbook_step(self, run_id: str, step_id: str) -> dict:
    """Execute one ``PlaybookRunStep`` end-to-end.

    Lives on the ``llm`` queue (same as ``run_chat_turn``) because each step
    spawns a synchronous ``ToolExecution.apply()`` that already pushes work
    onto the ``heavy`` queue worker — we don't want to fight for that worker.
    """
    del self
    try:
        return runner.execute_step(run_id, step_id)
    except Exception:  # noqa: BLE001
        logger.exception("playbook step %s failed in worker", step_id)
        raise


__all__ = ["run_playbook_step"]
