"""Sync API routes — trigger and monitor Audible library sync."""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from audiblimey.db import get_cursor
from audiblimey.sync.audible import run_sync

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sync"])


@router.post("/sync/audible")
async def start_audible_sync(background_tasks: BackgroundTasks):
    """Trigger an Audible library sync.

    Creates a sync_jobs row, checks for concurrent runs, and launches
    the sync in a BackgroundTask. Returns the job ID and status.

    - 400 if no Audible account is configured for the user
    - 409 if a sync is already running
    """
    user_id = 1

    # Check that user has an Audible account configured
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM user_audible_accounts WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        account = cur.fetchone()

    if not account:
        raise HTTPException(
            status_code=400,
            detail="No Audible account configured. Please link your Audible account first.",
        )

    # Prevent concurrent syncs
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM sync_jobs
            WHERE user_id = %s AND status = 'running'
            LIMIT 1
            """,
            (user_id,),
        )
        running_job = cur.fetchone()

    if running_job:
        raise HTTPException(
            status_code=409,
            detail="A sync is already running. Please wait for it to complete.",
        )

    # Create sync job
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_jobs (user_id, job_type, status)
            VALUES (%s, 'library_sync', 'pending')
            RETURNING id
            """,
            (user_id,),
        )
        job_row = cur.fetchone()
        job_id = job_row[0]

    # Launch background sync
    background_tasks.add_task(run_sync, user_id, job_id)

    logger.info("sync.start_audible_sync: launched job_id=%d for user_id=%d", job_id, user_id)

    return {"job_id": job_id, "status": "started"}


@router.get("/sync/status")
async def get_sync_status():
    """Get the latest sync job status for the current user."""
    user_id = 1

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, job_type, status, started_at, completed_at,
                   books_processed, books_added, books_updated,
                   error_message, created_at
            FROM sync_jobs
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"status": "no_syncs", "message": "No sync jobs found"}

    (
        job_id, job_type, status, started_at, completed_at,
        books_processed, books_added, books_updated,
        error_message, created_at,
    ) = row

    return {
        "job_id": job_id,
        "job_type": job_type,
        "status": status,
        "started_at": started_at.isoformat() if started_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "books_processed": books_processed,
        "books_added": books_added,
        "books_updated": books_updated,
        "error_message": error_message,
        "created_at": created_at.isoformat() if created_at else None,
    }
