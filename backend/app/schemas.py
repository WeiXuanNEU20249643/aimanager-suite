from datetime import date
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
Role = Literal['admin', 'member', 'observer']
Status = Literal['待办', '进行中', '待验收', '已完成']
Sprint = Literal['S1', 'S2', 'S3', 'S4', 'S5', 'S6']
Priority = Literal['Must', 'Should', 'Could', "Won't"]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LoginIn(Input):
    username: Text
    password: str = Field(min_length=1, max_length=1024, repr=False)


class MemberIn(Input):
    username: Text
    role: Text


class RoleIn(Input):
    role: Text


class RequirementIn(Input):
    title: Text
    description: LongText
    source: Text
    priority: Priority = 'Must'
    acceptance_criteria: LongText = '待补充验收条件'
    story_role: str = Field(default='', max_length=200)

    @field_validator('story_role')
    @classmethod
    def clean_story_role(cls, value):
        return value.strip()


class RequirementEdit(Input):
    title: Text
    description: LongText
    source: Text
    priority: Priority
    acceptance_criteria: LongText
    story_role: str | None = Field(default=None, max_length=200)
    version: int = Field(gt=0)
    reason: LongText

    @field_validator('story_role')
    @classmethod
    def clean_story_role(cls, value):
        return value.strip() if value is not None else None


class TaskIn(Input):
    title: Text
    requirement_id: Text
    description: str = Field(default='', max_length=10000)
    owner_id: int | None = Field(default=None, gt=0, le=9223372036854775807, strict=True)
    due_date: date | None = None
    sprint: Sprint = 'S1'
    milestone_id: int | None = Field(default=None, gt=0, le=9223372036854775807, strict=True)


class TaskEdit(Input):
    title: Text
    description: str = Field(max_length=10000)
    owner_id: int | None = Field(gt=0, le=9223372036854775807, strict=True)
    due_date: date | None
    sprint: Sprint
    milestone_id: int | None = Field(default=None, gt=0, le=9223372036854775807, strict=True)
    version: int = Field(gt=0)


class StatusIn(Input):
    status: Status
    version: int = Field(gt=0)
    reason: str = Field(default='', max_length=2000)
    acceptance_confirmed: bool = False


class TaskSourceIn(Input):
    requirement_id: Text
    version: int = Field(gt=0)
    reason: LongText


class DependencyIn(Input):
    depends_on_id: Text
    reason: LongText


class DependencyRemoveIn(Input):
    reason: LongText


class BlockerIn(Input):
    blocked: bool
    reason: str = Field(max_length=2000)
    version: int = Field(gt=0)

    @field_validator('reason')
    @classmethod
    def blocker_reason(cls, value, info):
        if info.data.get('blocked') and not value.strip():
            raise ValueError('阻塞原因必填')
        return value.strip()


class TaskPlanIn(Input):
    estimated_hours: float = Field(ge=0, le=100000)
    actual_hours: float = Field(ge=0, le=100000)
    remaining_hours: float = Field(ge=0, le=100000)
    planned_start: date | None = None
    planned_end: date | None = None
    plan_locked: bool = False
    required_skills: list[Text] = Field(default_factory=list, max_length=20)
    version: int = Field(gt=0)
    reason: str = Field(default='', max_length=2000)

    @field_validator('required_skills')
    @classmethod
    def unique_required_skills(cls, value):
        normalized = [item.casefold() for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError('任务技能要求不能重复')
        return value

    @model_validator(mode='after')
    def valid_plan_dates(self):
        if self.planned_start and self.planned_end and self.planned_end < self.planned_start:
            raise ValueError('计划结束日期不能早于开始日期')
        return self


class TaskActionIn(Input):
    version: int = Field(gt=0)
    reason: LongText


class CapacityIn(Input):
    weekly_capacity_hours: float = Field(ge=0, le=168)
    available_from: date | None = None
    available_to: date | None = None
    skill_tags: list[Text] = Field(default_factory=list, max_length=50)
    version: int = Field(ge=0)
    reason: str = Field(default='', max_length=2000)

    @field_validator('skill_tags')
    @classmethod
    def unique_skills(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('技能标签不能重复')
        return value

    @model_validator(mode='after')
    def valid_availability_dates(self):
        if self.available_from and self.available_to and self.available_to < self.available_from:
            raise ValueError('可用结束日期不能早于开始日期')
        return self


class ReplanIn(Input):
    requirement_version: int = Field(gt=0)
    plan_version: int = Field(ge=0)
    reason: LongText


class UseCaseGenerateIn(Input):
    source_version: int = Field(ge=0)


class SequenceMessageIn(Input):
    from_participant: Text
    to_participant: Text
    label: Text
    branch_condition: str = Field(default='', max_length=200)
    task_id: str | None = Field(default=None, max_length=32)

    @field_validator('branch_condition')
    @classmethod
    def clean_branch_condition(cls, value):
        return value.strip()


class SequenceScenarioIn(Input):
    name: Text
    description: str = Field(default='', max_length=2000)
    participants: list[Text] = Field(min_length=2, max_length=12)
    messages: list[SequenceMessageIn] = Field(min_length=1, max_length=100)

    @field_validator('description')
    @classmethod
    def clean_description(cls, value):
        return value.strip()


class SequenceScenarioEdit(SequenceScenarioIn):
    version: int = Field(gt=0)


class SequenceGenerateIn(Input):
    scenario_version: int = Field(gt=0)


class AIPRDBreakdownIn(Input):
    source_name: Text
    prd_text: LongText


class AIForecastIn(Input):
    as_of_date: date | None = None


class AIScheduleIn(Input):
    start_date: date | None = None


class AIRiskIn(Input):
    as_of_date: date | None = None
    overload_percent: float = Field(default=100, ge=1, le=1000)
    blocked_workdays: float = Field(default=1, ge=0, le=365)
    threshold_reason: str = Field(default='', max_length=2000)

    @field_validator('threshold_reason')
    @classmethod
    def clean_threshold_reason(cls, value):
        return value.strip()


class QualityArtifactIn(Input):
    artifact_type: Literal['code', 'document', 'test_report']
    file_name: Text
    version: Text
    content_scope: Text
    content: LongText


class AIQualityIn(Input):
    target_requirement_id: Text
    owner_id: int | None = Field(default=None, gt=0, le=9223372036854775807, strict=True)
    due_date: date | None = None
    artifacts: list[QualityArtifactIn] = Field(min_length=3, max_length=30)

    @model_validator(mode='after')
    def all_artifact_types(self):
        present = {item.artifact_type for item in self.artifacts}
        required = {'code', 'document', 'test_report'}
        if not required.issubset(present):
            raise ValueError('代码、文档和测试报告三类输入均至少提供一个样例')
        return self


class AIEfficiencyIn(Input):
    as_of_date: date | None = None


class AIOutputEditIn(Input):
    version: int = Field(gt=0)
    output: dict[str, Any]
    reason: LongText


class AIReviewIn(Input):
    version: int = Field(gt=0)
    reason: LongText
    operation_id: str | None = Field(default=None, min_length=8, max_length=200)

    @field_validator('operation_id')
    @classmethod
    def clean_operation_id(cls, value):
        return value.strip() if value is not None else None


class ImprovementActionEditIn(Input):
    status: Literal['待处理', '进行中', '已完成']
    version: int = Field(gt=0)
    current_metric_value: float | None = Field(default=None, ge=0, le=1000000000)
    review_note: str = Field(default='', max_length=10000)

    @field_validator('review_note')
    @classmethod
    def clean_review_note(cls, value):
        return value.strip()


class MilestoneIn(Input):
    name: Text
    target_date: date


class MilestoneEdit(MilestoneIn):
    version: int = Field(gt=0)


class CustomRoleIn(Input):
    name: Text
    description: str = Field(default='', max_length=2000)


class CustomRoleEdit(CustomRoleIn):
    permissions: list[Text]
    version: int = Field(gt=0)
