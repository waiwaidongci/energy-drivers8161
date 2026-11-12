from sqlalchemy import String,ForeignKey,JSON,DateTime,Integer,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from datetime import datetime
from src.config.database import Base
class ModelRun(Base):
    __tablename__='model_runs'
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(160),unique=True)
    dataset_id:Mapped[int]=mapped_column(ForeignKey('building_datasets.id'))
    config:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(20),default='queued')
    result:Mapped[dict]=mapped_column(JSON,default=dict)
    error:Mapped[str]=mapped_column(String(600),default='')
    attempt_count:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    updated_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
class RunAttempt(Base):
    __tablename__='run_attempts'
    __table_args__=(UniqueConstraint('run_id','active_key',name='uq_run_active_attempt'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    run_id:Mapped[int]=mapped_column(ForeignKey('model_runs.id'))
    attempt_no:Mapped[int]=mapped_column(Integer)
    status:Mapped[str]=mapped_column(String(20),default='queued')
    stage:Mapped[str]=mapped_column(String(30),default='queued')
    progress:Mapped[int]=mapped_column(Integer,default=0)
    detail:Mapped[str]=mapped_column(String(600),default='')
    error:Mapped[str]=mapped_column(String(600),default='')
    # 活动尝试（queued/running）时等于run_id，终态置NULL；配合唯一索引保证每个研究至多一个活动尝试
    active_key:Mapped[int|None]=mapped_column(Integer,nullable=True)
    started_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    finished_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
