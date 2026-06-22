import os
import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

try:
    # Use decode_responses=True to handle strings automatically
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    # Ping to test connection
    redis_client.ping()
    print(f"[Redis] Connected successfully to {REDIS_URL}")
except Exception as e:
    print(f"[Redis] Connection failed: {e}")
    redis_client = None
