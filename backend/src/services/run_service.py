import json,hashlib
from sqlalchemy import select
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.constants.enums import RunStatus,AttemptStatus,ProgressStage
from src.models import BuildingDataset,ModelRun,RunAttempt
from src.services import run_lifecycle as lifecycle
from src.services.day_service import raw_days
from src.services.splitting import training_arrays
from src.services.learning import fit_grouped
from src.services.inspection import inspect_holdout
queue=Redis.from_url(REDIS_URL)

def _attempt_dict(attempt):
    return {'id':attempt.id,'attempt_no':attempt.attempt_no,'status':attempt.status,'stage':attempt.stage,
            'progress':attempt.progress,'detail':attempt.detail,'error':attempt.error,
            'started_at':attempt.started_at.isoformat() if attempt.started_at else None,
            'finished_at':attempt.finished_at.isoformat() if attempt.finished_at else None,
            'created_at':attempt.created_at.isoformat() if attempt.created_at else None}

def serialize_run(db,run):
    return {'id':run.id,'name':run.name,'dataset_id':run.dataset_id,'config':run.config,'status':run.status,
            'error':run.error,'result':run.result or {},'attempt_count':run.attempt_count,
            'created_at':run.created_at.isoformat() if run.created_at else None,
            'updated_at':run.updated_at.isoformat() if run.updated_at else None,
            'attempts':[_attempt_dict(a) for a in lifecycle.attempts_for(db,run.id)]}

def list_runs(db):return [serialize_run(db,run) for run in db.scalars(select(ModelRun).order_by(ModelRun.id.desc())).all()]
def get_run(db,id):
    run=db.get(ModelRun,id)
    if not run:raise HTTPException(404,'模型研究不存在')
    return serialize_run(db,run)
def create_run(db,data):
    dataset=db.scalar(select(BuildingDataset).where(BuildingDataset.id==data.dataset_id).with_for_update())
    if not dataset:raise HTTPException(404,'数据集不存在')
    config=data.config()
    if dataset.locked_config is not None and dataset.locked_config!=config:raise HTTPException(409,'数据集选模配置已锁定；公开封存评估后不得改特征或超参，只能同配置复算')
    if db.scalar(select(ModelRun).where(ModelRun.name==data.name)):raise HTTPException(409,'研究名称已存在')
    try:training_arrays(raw_days(db,dataset.id),config)
    except ValueError as exc:raise HTTPException(422,str(exc))
    dataset.locked_config=config
    run=ModelRun(name=data.name,dataset_id=dataset.id,config=config,status=RunStatus.QUEUED,attempt_count=1)
    db.add(run);db.flush()
    db.add(RunAttempt(run_id=run.id,attempt_no=1,status=AttemptStatus.QUEUED,stage=ProgressStage.QUEUED,
                      detail='配置已锁定，等待worker领取',active_key=run.id))
    db.commit();queue.lpush('energy:runs',str(run.id));return serialize_run(db,run)

def cancel_run(db,id):return serialize_run(db,lifecycle.cancel_run(db,id))

def retry_run(db,id):
    run,attempt=lifecycle.retry_run(db,id)
    queue.lpush('energy:runs',str(run.id))
    return serialize_run(db,run)

def _checkpoint(db,run,attempt,stage,percent,detail=''):
    if lifecycle.cancel_requested(db,run.id):
        raise lifecycle.RunCancelled('研究已取消')
    if not lifecycle.update_progress(db,attempt,stage,percent,detail):
        raise lifecycle.RunCancelled('研究已取消或已被新尝试替代')

def execute_run(db,id):
    run=db.get(ModelRun,id)
    if not run or run.status not in lifecycle.ACTIVE_RUN_STATES:return
    attempt=lifecycle.start_attempt(db,id)
    if attempt is None:
        if run.status in lifecycle.ACTIVE_RUN_STATES and not lifecycle.active_attempt(db,id):
            run.status=RunStatus.FAILED;run.error='缺少活动尝试，请使用重试重新发起计算';db.commit()
        return
    try:
        dataset=db.get(BuildingDataset,run.dataset_id);rows=raw_days(db,dataset.id)
        progress=lambda stage,percent,detail='':_checkpoint(db,run,attempt,stage,percent,detail)
        model,report=fit_grouped(rows,run.config,progress)
        _checkpoint(db,run,attempt,ProgressStage.HOLDOUT,78,'读取封存楼宇并评估最终成绩')
        metrics,findings,points=inspect_holdout(model,report,rows,run.config,progress)
        _checkpoint(db,run,attempt,ProgressStage.PERSIST,97,'写入驱动解释与封存评估')
        snapshot={'algorithm':'elasticnet-building-v1','dataset_id':dataset.id,'rows':rows,'config':run.config,'split':report['split']}
        fingerprint=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        # Recovery can rerun an interrupted job; findings are written in the same final transaction.
        result={**report,'metrics':metrics,'points':points,'input_fingerprint':fingerprint,'config':run.config}
        if not lifecycle.publish_completion(db,run.id,attempt.id,result,findings):
            return
    except lifecycle.RunCancelled:
        db.rollback()
        # 取消请求或更新的尝试已经记录终态；旧计算不会公开封存结果。
        current=db.get(ModelRun,id)
        if current is not None and current.status in lifecycle.ACTIVE_RUN_STATES:
            lifecycle.fail_run(db,id,attempt.id,'研究已取消')
    except Exception as exc:
        db.rollback()
        lifecycle.fail_run(db,id,attempt.id,exc)
