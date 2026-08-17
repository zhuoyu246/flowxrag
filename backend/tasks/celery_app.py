"""
Celery 实例配置
- Broker: Redis (db=1)
- Result Backend: Redis (db=2)
- Beat Schedule: 定时任务（每日重建索引、清理过期记录）
"""
from __future__ import annotations

import os
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv(override=True)

# Redis URL（Celery 使用独立 db，避免与问答缓存冲突）
_redis_base = os.getenv("REDIS_URL", "redis://localhost:6379")
_broker_url = os.getenv("CELERY_BROKER_URL", _redis_base.rstrip("/0") + "/1")
_result_backend = os.getenv("CELERY_RESULT_BACKEND", _redis_base.rstrip("/0") + "/2")

celery_app = Celery(
    "crag_tasks",
    broker=_broker_url,
    backend=_result_backend,
    include=[
        "backend.tasks.document_tasks",
        "backend.tasks.scheduled_tasks",
    ],
)

celery_app.conf.update(
    # 序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务结果保留 24 小时
    result_expires=86400,
    # 重试策略
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Worker 并发数（CPU 密集用 prefork，IO 密集用 gevent）
    worker_concurrency=4,
    worker_prefetch_multiplier=1,
    # Beat 定时任务
    beat_schedule={
        # 每天凌晨 3:00 重建向量索引
        "rebuild-index-daily": {
            "task": "backend.tasks.scheduled_tasks.rebuild_index_task",
            "schedule": crontab(hour=3, minute=0),
        },
        # 每小时清理 7 天前的任务记录
        "cleanup-old-task-records": {
            "task": "backend.tasks.scheduled_tasks.cleanup_old_tasks_task",
            "schedule": crontab(minute=30),
            "args": (7,),
        },
        # 每 5 分钟上报健康指标到日志
        "health-metrics-report": {
            "task": "backend.tasks.scheduled_tasks.report_health_metrics",
            "schedule": 300.0,
        },
    },
)
