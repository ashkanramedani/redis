import redis.asyncio as aioredis
from fastapi_limiter import FastAPILimiter

async def initialize_rate_limiter(redis_url: str):
    redis = aioredis.from_url(redis_url, encoding="utf8", decode_responses=True)
    await FastAPILimiter.init(redis)
