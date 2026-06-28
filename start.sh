#!/bin/sh

# Start the Celery worker in the background.
# Using solo pool because we run inside a container with limited resources
# and don't need prefork multiprocessing.
celery -A celery_worker.celery_app worker \
    --loglevel=info \
    --pool=solo \
    --concurrency=1 &

# Start the FastAPI server in the foreground.
# This keeps the container alive — if uvicorn exits, the container stops.
exec uvicorn main:app --host 0.0.0.0 --port 8000
