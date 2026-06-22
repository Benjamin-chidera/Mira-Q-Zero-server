import os
import json
from celery import Celery
from utils.mira.ai_research import run_mira_research
from utils.redis_client import redis_client

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "mira_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL
)

@celery_app.task(name="process_research_task")
def process_research_task(conversation_id: str, practitioner_id: int, content: str, attachments: list, sid: str):
    """
    Asynchronously executes Mira LangGraph research.
    Publishes completion results to Redis Pub/Sub for frontend delivery.
    """
    print(f"[Celery] Processing research task for conv={conversation_id}, sid={sid}")
    try:
        result = run_mira_research(
            conversation_id=conversation_id,
            practitioner_id=practitioner_id,
            query=content,
            attachments=attachments
        )
        
        # Publish the response payload to Redis Pub/Sub
        if redis_client:
            payload = {
                "conversation_id": conversation_id,
                "sid": sid,
                "response": result["response"],
                "sources": result["sources"]
            }
            redis_client.publish("mira_responses", json.dumps(payload))
            print(f"[Celery] Successfully published response to mira_responses for conv={conversation_id}")
            
    except Exception as e:
        print(f"[Celery] Error in process_research_task: {e}")
        # Publish failure status to Redis Pub/Sub
        if redis_client:
            payload = {
                "conversation_id": conversation_id,
                "sid": sid,
                "error": str(e)
            }
            redis_client.publish("mira_responses", json.dumps(payload))
