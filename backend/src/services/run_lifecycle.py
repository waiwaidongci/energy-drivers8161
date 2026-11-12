from datetime import datetime
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.constants.enums import RunStatus,AttemptStatus,ProgressStage
from src.models import ModelRun,RunAttempt,DriverFinding,BuildingDataset

ACTIVE_RUN_STATES=(RunStatus.QUEUED,RunStatus.RUNNING)
ACTIVE_ATTEMPT_STATES=(AttemptStatus.QUEUED,AttemptStatus.RUNNING)

class RunCancelled(Exception):
    """worker 在计算检查点发现研究已取消。"""

def _now():return datetime.utcnow()

def attempts_for(db,run_id):
    return db.scalars(select(RunAttempt).where(RunAttempt.run_id==run_id).order_by(RunAttempt.attempt_no)).all()

def active_attempt(db,run_id):
    return db.scalar(select(RunAttempt).where(RunAttempt.run_id==run_id,RunAttempt.status.in_(ACTIVE_ATTEMPT_STATES)).order_by(RunAttempt.attempt_no.desc()))

def _new_attempt(db,run,detail=''):
    next_no=int(db.scalar(select(func.max(RunAttempt.attempt_no)).where(RunAttempt.run_id==run.id)) or 0)+1
    attempt=RunAttempt(run_id=run.id,attempt_no=next_no,status=AttemptStatus.QUEUED,stage=ProgressStage.QUEUED,
                       progress=0,detail=detail,active_key=run.id)
    db.add(attempt);run.attempt_count=next_no
    return attempt

def _finish(attempt,status,error='',detail=None):
    attempt.status=str(status);attempt.active_key=None;attempt.finished_at=_now()
    if error:attempt.error=error[:600]
    if detail is not None:attempt.detail=detail[:600]

def start_attempt(db,run_id):
    """领取排队尝试；服务中断留下的运行中尝试标记失败后自动重新排队。"""
    run=db.get(ModelRun,run_id)
    if not run or run.status not in ACTIVE_RUN_STATES:return None
    attempt=db.scalar(select(RunAttempt).where(RunAttempt.run_id==run_id,RunAttempt.status==AttemptStatus.QUEUED).order_by(RunAttempt.attempt_no).with_for_update())
    if attempt is None:
        stale=db.scalar(select(RunAttempt).where(RunAttempt.run_id==run_id,RunAttempt.status==AttemptStatus.RUNNING).order_by(RunAttempt.attempt_no.desc()))
        if stale is None:return None
        _finish(stale,AttemptStatus.FAILED,error='worker服务中断，研究恢复后自动重新排队')
        attempt=_new_attempt(db,run,'接续中断的第%d次尝试'%stale.attempt_no);db.commit()
        db.refresh(attempt)
    attempt.status=AttemptStatus.RUNNING;attempt.stage=ProgressStage.QUEUED;attempt.progress=max(attempt.progress,0)
    attempt.error='';attempt.started_at=_now()
    run.status=RunStatus.RUNNING;run.error=''
    db.commit();db.refresh(attempt)
    return attempt

def update_progress(db,attempt,stage,percent,detail=''):
    """提交一次进度；若尝试已被取消/替代则返回False，worker据此停止计算。"""
    db.refresh(attempt)
    if attempt.status!=AttemptStatus.RUNNING:return False
    attempt.stage=str(stage);attempt.progress=max(attempt.progress,min(100,int(percent)));attempt.detail=detail[:600]
    db.commit()
    return True

def cancel_requested(db,run_id):
    run=db.get(ModelRun,run_id)
    if run:db.refresh(run)
    return bool(run and run.status==RunStatus.CANCELLED)

def cancel_run(db,run_id):
    run=db.get(ModelRun,run_id)
    if not run:raise HTTPException(404,'模型研究不存在')
    if run.status not in ACTIVE_RUN_STATES:raise HTTPException(409,'只有排队或运行中的研究可以取消')
    run.status=RunStatus.CANCELLED;run.error='研究已由分析员取消';run.result={}
    now=_now()
    for attempt in db.scalars(select(RunAttempt).where(RunAttempt.run_id==run_id,RunAttempt.status.in_(ACTIVE_ATTEMPT_STATES))).all():
        _finish(attempt,AttemptStatus.CANCELLED,detail='等待worker确认取消；旧计算即使稍后结束也不会公开封存结果')
    # 取消不允许留下任何驱动解释（正常情况下仅终态事务会写入，这里是兜底清理）
    for finding in db.scalars(select(DriverFinding).where(DriverFinding.run_id==run_id)).all():db.delete(finding)
    db.commit()
    return run

def retry_run(db,run_id):
    run=db.get(ModelRun,run_id)
    if not run:raise HTTPException(404,'模型研究不存在')
    if run.status not in (RunStatus.FAILED,RunStatus.CANCELLED):raise HTTPException(409,'只有未完成或已取消的研究可以重试')
    if active_attempt(db,run_id):raise HTTPException(409,'重试已在进行中，重复点击不会产生新的计算')
    if db.scalar(select(RunAttempt).where(RunAttempt.run_id==run_id,RunAttempt.status==AttemptStatus.COMPLETED)):
        raise HTTPException(409,'研究已有成功尝试，不能重复计算')
    # 重试沿用数据集最初锁定的方案：config 保持不变，仅新增一次尝试；
    # 唯一索引 uq_run_active_attempt 在数据库层兜底，并发重复点击只有一次能插入。
    attempt=_new_attempt(db,run,'沿用锁定配置的第%d次尝试'%(run.attempt_count+1))
    run.status=RunStatus.QUEUED;run.error='';run.result={}
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'重试已在进行中，重复点击不会产生新的计算')
    return run,attempt

def publish_completion(db,run_id,attempt_id,result,findings):
    """唯一的成功封存入口：守护取消与过期尝试，全部内容在同一事务写入。"""
    run=db.get(ModelRun,run_id);attempt=db.get(RunAttempt,attempt_id)
    if run is None or attempt is None:return False
    if run.status==RunStatus.CANCELLED or attempt.status!=AttemptStatus.RUNNING:
        attempt=db.get(RunAttempt,attempt_id)
        if attempt and attempt.status in ACTIVE_ATTEMPT_STATES:
            _finish(attempt,AttemptStatus.CANCELLED,detail='计算结束时研究已取消或已被新尝试替代，旧结果不予封存')
            db.commit()
        return False
    existing={f.feature:f for f in db.scalars(select(DriverFinding).where(DriverFinding.run_id==run_id)).all()}
    for values in findings:
        if values['feature'] not in existing:db.add(DriverFinding(run_id=run_id,**values))
    run.result=result;run.status=RunStatus.COMPLETED;run.error=''
    _finish(attempt,AttemptStatus.COMPLETED)
    attempt.stage=ProgressStage.PERSIST;attempt.progress=100;attempt.error=''
    db.get(BuildingDataset,run.dataset_id).evaluation_released=True
    db.commit()
    return True

def fail_run(db,run_id,attempt_id,error):
    """失败落账；已取消或已被新尝试替代的旧尝试不能覆盖研究当前状态。"""
    run=db.get(ModelRun,run_id);attempt=db.get(RunAttempt,attempt_id)
    if run is None or attempt is None:return
    message=str(error)[:600]
    if run.status==RunStatus.CANCELLED or attempt.status!=AttemptStatus.RUNNING:
        if attempt.status in ACTIVE_ATTEMPT_STATES:
            _finish(attempt,AttemptStatus.CANCELLED,detail='研究已取消或已被新尝试替代，本次中断不改变研究状态')
            db.commit()
        return
    _finish(attempt,AttemptStatus.FAILED,error=message)
    run.status=RunStatus.FAILED;run.error=message
    db.commit()
