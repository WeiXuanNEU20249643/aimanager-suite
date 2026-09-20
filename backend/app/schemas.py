from datetime import date
from typing import Annotated, Literal
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


class RequirementEdit(Input):
    title: Text
    description: LongText
    source: Text
    priority: Priority
    acceptance_criteria: LongText
    version: int = Field(gt=0)
    reason: LongText


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
    version: int = Field(gt=0)
    reason: str = Field(default='', max_length=2000)

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
