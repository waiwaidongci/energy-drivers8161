import time
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import ModelRun
from src.constants.enums import RunStatus
from src.services.run_service import execute_run
redis=Redis.from_url(REDIS_URL)
def recover():
    """启动恢复：仍排队/运行的研究重新入队续跑；已取消的研究保持取消，不会被旧消息覆盖。"""
    with Session() as db:
        ids=[r.id for r in db.scalars(select(ModelRun).where(ModelRun.status.in_([RunStatus.QUEUED,RunStatus.RUNNING])).order_by(ModelRun.id)).all()]
    for run_id in ids:redis.lpush('energy:runs',str(run_id))
    return ids
def process_once():
    """处理一条队列消息；无消息时做一次兜底巡检。返回是否消费了消息。"""
    item=redis.brpop('energy:runs',timeout=2)
    if item:
        try:run_id=int(item[1])
        except ValueError:return False
        with Session() as db:execute_run(db,run_id)
        return True
    # 兜底巡检：消息丢失时为仍活动的研究补一条唤醒；execute_run 与尝试状态保证幂等。
    with Session() as db:
        due=db.scalars(select(ModelRun).where(ModelRun.status.in_([RunStatus.QUEUED,RunStatus.RUNNING])).order_by(ModelRun.id)).all()
        if due and redis.llen('energy:runs')==0:redis.lpush('energy:runs',str(due[0].id))
    return False
def main():
    recover()
    while True:
        Path('/tmp/heartbeat').touch()
        process_once()
        time.sleep(.1)
if __name__=='__main__':main()
