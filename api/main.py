from fastapi import FastAPI, Depends, Header, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter.depends import RateLimiter
from pydantic import BaseModel, Field
from typing import Optional, Union
from datetime import datetime
import json
import os
import redis
import sqlite3
import sys

sys.path.append(r"libs")
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')

from apikey_manager import initialize_db, add_api_key, validate_api_key_dependency
from metrics import metrics_app, REQUEST_LATENCY, REQUEST_COUNT
from rate_limiter import initialize_rate_limiter
from logging_config import setup_logging

# بارگذاری تنظیمات از فایل config.json
CONFIG_PATH = "config/config.json"
if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

with open(CONFIG_PATH, "r") as config_file:
    config = json.load(config_file)

REDIS_URL = f"redis://:{config['REDIS_PASSWORD']}@{config['REDIS_HOST']}:{config['REDIS_PORT']}/0"
ADMIN_API_KEY = config["ADMIN_API_KEY"]

# تنظیمات لاگ
logger = setup_logging()

# مدل‌های ورودی و خروجی
class KeyValueInput(BaseModel):
    key: str
    value: str
    db_index: int = Field(0, ge=0, le=15)
    ttl: Optional[int] = Field(None, ge=1)

class KeyValueOutput(BaseModel):
    key: str
    value: Optional[str]
    ttl: Optional[int]
    db_index: int
    message: str

class TTLResponse(BaseModel):
    key: str
    ttl: Union[int, str]
    db_index: int

# برنامه FastAPI
app = FastAPI()

# دیکشنری کانکشن‌ها
redis_connections = {}

# افزودن CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# مونت کردن متریک‌ها
app.mount("/metrics", metrics_app)

# مقداردهی اولیه
@app.on_event("startup")
async def startup():
    logger.info("Starting application...")
    initialize_db()
    await initialize_rate_limiter(REDIS_URL)
    logger.info("Application started successfully.")

@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down application.")

# Middleware برای رهگیری درخواست‌ها و محاسبه متریک‌ها
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    endpoint = request.url.path
    method = request.method
    ip_address = request.client.host
    logger.info(f"Request from IP: {ip_address}, Endpoint: {endpoint}, Method: {method}")
    with REQUEST_LATENCY.labels(endpoint=endpoint).time():
        response = await call_next(request)
        status_code = response.status_code
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status_code)).inc()
    return response

# Middleware برای Rate Limiting
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path == '/metrics':
        return await call_next(request)

    client_ip = request.client.host
    key_prefix = 'rate_limit'
    now = int(datetime.utcnow().timestamp())
    window_size = 60  # 1-minute window
    window_start = now - (now % window_size)
    ip_key = f"{key_prefix}:ip:{client_ip}:{window_start}"
    global_key = f"{key_prefix}:global:{window_start}"

    # Global rate limit
    global_limit = 1000  # Global limit of 1000 requests per minute

    if client_ip == '127.0.0.1':
        ip_limit = 100  # Higher limit for localhost
    else:
        ip_limit = 5  # Default limit
        country_code = 'unknown'
        ip_limit = 5  # Default limit when GeoIP is unavailable
        
    response = await call_next(request)
    return response

# اعتبارسنجی db_index
def validate_db_index(db_index: int, max_dbs: int = 15):
    if not isinstance(db_index, int) or db_index < 0 or db_index > max_dbs:
        raise ValueError(f"db_index must be an integer between 0 and {max_dbs}.")

# دریافت اتصال Redis همگام (برای عملیات داده)
def get_redis_connection(db_index: int, max_retries: int = 3, max_dbs: int = 15):
    validate_db_index(db_index, max_dbs)
    for attempt in range(max_retries):
        try:
            if db_index not in redis_connections or not redis_connections[db_index].ping():
                redis_connections[db_index] = redis.Redis(
                    host=config['REDIS_HOST'],
                    port=config['REDIS_PORT'],
                    password=config['REDIS_PASSWORD'],
                    decode_responses=True,
                    db=db_index,
                )
            return redis_connections[db_index]
        except (redis.ConnectionError, redis.TimeoutError) as e:
            if attempt == max_retries - 1:
                raise Exception(f"Failed to connect to Redis on db_index {db_index} after {max_retries} attempts.") from e

# مدل‌ها و روترها
@app.post("/create", response_model=KeyValueOutput, dependencies=[Depends(validate_api_key_dependency), Depends(RateLimiter(times=10, seconds=5))])
async def create_key(data: KeyValueInput):
    """ایجاد کلید جدید"""
    logger.info(f"Request to create key: {data.key} in db_index: {data.db_index}")
    try:
        r = get_redis_connection(data.db_index)
        if r.exists(data.key):
            logger.warning(f"Key {data.key} already exists in db_index: {data.db_index}")
            raise HTTPException(status_code=400, detail="Key already exists")
        if data.ttl:
            r.set(data.key, data.value, ex=data.ttl)
        else:
            r.set(data.key, data.value)
        logger.info(f"Key {data.key} created successfully in db_index: {data.db_index}")
        return KeyValueOutput(
            key=data.key,
            value=data.value,
            ttl=data.ttl,
            db_index=data.db_index,
            message="Key created successfully"
        )
    except Exception as e:
        logger.error(f"Error creating key {data.key}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/update", response_model=KeyValueOutput, dependencies=[Depends(validate_api_key_dependency), Depends(RateLimiter(times=10, seconds=5))])
async def update_key(data: KeyValueInput):
    """به‌روزرسانی کلید موجود"""
    logger.info(f"Request to update key: {data.key} in db_index: {data.db_index}")
    try:
        r = get_redis_connection(data.db_index)
        if not r.exists(data.key):
            logger.warning(f"Key {data.key} not found in db_index: {data.db_index}")
            raise HTTPException(status_code=404, detail="Key not found")
        if data.ttl:
            r.set(data.key, data.value, ex=data.ttl)
        else:
            r.set(data.key, data.value)
        logger.info(f"Key {data.key} updated successfully in db_index: {data.db_index}")
        return KeyValueOutput(
            key=data.key,
            value=data.value,
            ttl=data.ttl,
            db_index=data.db_index,
            message="Key updated successfully"
        )
    except Exception as e:
        logger.error(f"Error updating key {data.key}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get", response_model=KeyValueOutput, dependencies=[Depends(validate_api_key_dependency), Depends(RateLimiter(times=10, seconds=5))])
async def get_key(key: str, db_index: int = Query(0)):
    """دریافت مقدار کلید"""
    logger.info(f"Request to get key: {key} from db_index: {db_index}")
    try:
        r = get_redis_connection(db_index)
        if not r.exists(key):
            logger.warning(f"Key {key} not found in db_index: {db_index}")
            raise HTTPException(status_code=404, detail="Key not found")
        value = r.get(key)
        ttl = r.ttl(key)
        logger.info(f"Key {key} retrieved successfully from db_index: {db_index}")
        return KeyValueOutput(
            key=key,
            value=value,
            ttl=ttl if ttl != -1 else None,
            db_index=db_index,
            message="Key retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error retrieving key {key}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete", dependencies=[Depends(validate_api_key_dependency), Depends(RateLimiter(times=10, seconds=5))])
async def delete_key(key: str, db_index: int = Query(0)):
    """حذف کلید"""
    logger.info(f"Request to delete key: {key} from db_index: {db_index}")
    try:
        r = get_redis_connection(db_index)
        if not r.exists(key):
            logger.warning(f"Key {key} not found in db_index: {db_index}")
            raise HTTPException(status_code=404, detail="Key not found")
        r.delete(key)
        logger.info(f"Key {key} deleted successfully from db_index: {db_index}")
        return {"message": "Key deleted successfully", "key": key}
    except Exception as e:
        logger.error(f"Error deleting key {key}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ttl", response_model=TTLResponse, dependencies=[Depends(validate_api_key_dependency), Depends(RateLimiter(times=10, seconds=5))])
async def get_ttl(key: str, db_index: int = Query(0)):
    """بررسی TTL یک کلید"""
    logger.info(f"Request to get TTL for key: {key} in db_index: {db_index}")
    try:
        r = get_redis_connection(db_index)
        ttl = r.ttl(key)
        if ttl == -2:
            logger.warning(f"Key {key} not found in db_index: {db_index}")
            raise HTTPException(status_code=404, detail="Key not found")
        ttl_value = ttl if ttl != -1 else "No TTL set"
        logger.info(f"TTL for key {key} in db_index {db_index}: {ttl_value}")
        return TTLResponse(
            key=key,
            ttl=ttl_value,
            db_index=db_index
        )
    except Exception as e:
        logger.error(f"Error getting TTL for key {key}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/add_apikey")
def add_apikey(api_key: str, description: Optional[str] = None, x_api_key: str = Header(...)):
    """افزودن API Key جدید"""
    logger.info(f"Adding API Key: {api_key}")
    if x_api_key != ADMIN_API_KEY:
        logger.warning("Unauthorized attempt to add API Key.")
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        add_api_key(api_key, description)
        logger.info(f"API Key {api_key} added successfully.")
        return {"message": "API Key added successfully"}
    except sqlite3.IntegrityError:
        logger.error(f"API Key {api_key} already exists.")
        raise HTTPException(status_code=400, detail="API Key already exists")

