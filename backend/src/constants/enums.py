from enum import StrEnum
class Role(StrEnum):
    ADMIN='admin'
    ANALYST='analyst'
    VIEWER='viewer'
class RunStatus(StrEnum):
    QUEUED='queued'
    RUNNING='running'
    COMPLETED='completed'
    FAILED='failed'
    CANCELLED='cancelled'
class AttemptStatus(StrEnum):
    QUEUED='queued'
    RUNNING='running'
    COMPLETED='completed'
    FAILED='failed'
    CANCELLED='cancelled'
class HypothesisStatus(StrEnum):
    DRAFT='draft'
    APPROVED='approved'
class ProgressStage(StrEnum):
    QUEUED='queued'
    SPLIT='split'
    CV='cross_validation'
    FINAL_FIT='final_fit'
    HOLDOUT='holdout_eval'
    PERMUTATION='permutation'
    PERSIST='persist'
FEATURES=('temperature_c','operating_hours','area_m2','visitors','humidity_pct','equipment_kw','holiday_flag')
SPLIT_SEED=97
CV_SPLITS=3
