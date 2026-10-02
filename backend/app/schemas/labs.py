"""In-house lab: test catalog (admin), orders, samples and results."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.db.models import LabCategory, LabRangeSex, LabSampleType, LabValueType
from app.schemas.common import Name, ShortText, UtcDateTime

TestCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9_-]{1,20}$"),
]
ParameterCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9_-]{1,30}$"),
]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]
Choice = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class ReferenceRangeIn(BaseModel):
    sex: LabRangeSex = LabRangeSex.ANY
    age_min_years: int | None = Field(default=None, ge=0, le=150)
    age_max_years: int | None = Field(default=None, ge=0, le=150)
    low: float | None = None
    high: float | None = None
    critical_low: float | None = None
    critical_high: float | None = None
    text_normal: ShortText = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (
            self.age_min_years is not None
            and self.age_max_years is not None
            and self.age_min_years > self.age_max_years
        ):
            raise ValueError("Minimum age must not exceed maximum age.")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("Low must not exceed high.")
        if self.critical_low is not None and (
            (self.low is not None and self.critical_low > self.low)
            or (self.high is not None and self.critical_low >= self.high)
        ):
            raise ValueError("Critical low must be at or below the normal range.")
        if self.critical_high is not None and (
            (self.high is not None and self.critical_high < self.high)
            or (self.low is not None and self.critical_high <= self.low)
        ):
            raise ValueError("Critical high must be at or above the normal range.")
        return self


class ReferenceRangeOut(ReferenceRangeIn):
    id: UUID


class ParameterIn(BaseModel):
    # Set to keep (and update) an existing parameter; results reference parameters by id.
    id: UUID | None = None
    code: ParameterCode
    name: Name
    unit: Unit | None = None
    value_type: LabValueType = LabValueType.NUMERIC
    choices: list[Choice] = Field(default_factory=list, max_length=30)
    decimals: int = Field(default=1, ge=0, le=4)
    delta_percent: float | None = Field(default=None, gt=0, le=1000)
    is_active: bool = True
    ranges: list[ReferenceRangeIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _choices(self) -> Self:
        if (self.value_type == LabValueType.CHOICE) != bool(self.choices):
            raise ValueError("Choice parameters need choices; other types must not have any.")
        return self


class ParameterOut(BaseModel):
    id: UUID
    code: str
    name: str
    unit: str | None
    value_type: LabValueType
    choices: list[str]
    decimals: int
    delta_percent: float | None
    is_active: bool
    ranges: list[ReferenceRangeOut]


class LabTestIn(BaseModel):
    code: TestCode
    name: Name
    category: LabCategory
    sample_type: LabSampleType
    container: ShortText = None
    turnaround_hours: int = Field(default=24, ge=1, le=720)
    is_panel: bool = False
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=100000)
    parameters: list[ParameterIn] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def _unique_codes(self) -> Self:
        codes = [p.code for p in self.parameters]
        if len(codes) != len(set(codes)):
            raise ValueError("Parameter codes must be unique within a test.")
        return self


class LabTestActive(BaseModel):
    is_active: bool


class LabTestOut(BaseModel):
    id: UUID
    code: str
    name: str
    category: LabCategory
    sample_type: LabSampleType
    container: str | None
    turnaround_hours: int
    is_panel: bool
    is_active: bool
    sort_order: int
    parameters: list[ParameterOut]
    updated_at: UtcDateTime


class ClinicSettingsOut(BaseModel):
    lab_requires_verification: bool


class ClinicSettingsUpdate(BaseModel):
    lab_requires_verification: bool
