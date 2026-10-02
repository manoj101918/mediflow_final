"""In-house lab: test catalog (admin), orders, samples and results."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.db.models import (
    Gender,
    LabCategory,
    LabFlag,
    LabItemStatus,
    LabOrderStatus,
    LabPriority,
    LabRangeSex,
    LabSampleType,
    LabValueType,
)
from app.schemas.common import Name, NoteText, ShortText, UtcDateTime

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


# ---------------------------------------------------------------------------
# Orders, samples and results
# ---------------------------------------------------------------------------


class LabOrderCreate(BaseModel):
    test_ids: list[UUID] = Field(min_length=1, max_length=30)
    priority: LabPriority = LabPriority.ROUTINE
    clinical_note: NoteText = None


class LabCancel(BaseModel):
    # None cancels every test that is still waiting for collection.
    item_ids: list[UUID] | None = Field(default=None, max_length=30)
    reason: ShortText = None


class LabCollect(BaseModel):
    item_ids: list[UUID] = Field(min_length=1, max_length=30)


class LabReason(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class LabComment(BaseModel):
    comment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class LabValueIn(BaseModel):
    parameter_id: UUID
    # A number for numeric parameters, the text/choice otherwise; null clears a draft value.
    value: float | Annotated[str, StringConstraints(max_length=500)] | None


class LabResultsIn(BaseModel):
    values: list[LabValueIn] = Field(min_length=1, max_length=60)
    confirm_critical: bool = False


class LabAmendIn(BaseModel):
    values: list[LabValueIn] = Field(min_length=1, max_length=60)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class LabAcknowledge(BaseModel):
    note: NoteText = None


class LabResultOut(BaseModel):
    id: UUID
    parameter_id: UUID
    parameter_code: str
    parameter_name: str
    unit: str | None
    value_type: LabValueType
    value_numeric: float | None
    value_text: str | None
    range_label: str | None
    ref_low: float | None
    ref_high: float | None
    flag: LabFlag | None
    version: int
    is_current: bool
    amended_reason: str | None
    entered_at: UtcDateTime


class LabSampleOut(BaseModel):
    id: UUID
    sample_code: str
    sample_type: LabSampleType
    container: str | None
    collected_at: UtcDateTime
    rejected_at: UtcDateTime | None
    rejected_reason: str | None


class LabItemOut(BaseModel):
    id: UUID
    test_id: UUID
    test_code: str
    test_name: str
    status: LabItemStatus
    sample_id: UUID | None
    sample_code: str | None
    rejection_reason: str | None
    return_comment: str | None
    entered_at: UtcDateTime | None
    verified_at: UtcDateTime | None
    released_at: UtcDateTime | None
    cancelled_reason: str | None
    results: list[LabResultOut]
    # Earlier versions of amended results.
    history: list[LabResultOut]


class LabOrderOut(BaseModel):
    id: UUID
    order_number: str
    patient_id: UUID
    patient_name: str
    appointment_id: UUID
    consultation_id: UUID | None
    ordering_doctor_id: UUID
    ordering_doctor_name: str
    priority: LabPriority
    status: LabOrderStatus
    clinical_note: str | None
    cancelled_reason: str | None
    reviewed_at: UtcDateTime | None
    report_id: UUID | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    items: list[LabItemOut]
    samples: list[LabSampleOut]


class LabTestStatusOut(BaseModel):
    test_name: str
    status: LabItemStatus


class LabOrderStatusOut(BaseModel):
    """Front desk view of an order: no clinical note, no values."""

    id: UUID
    order_number: str
    appointment_id: UUID
    ordering_doctor_name: str
    priority: LabPriority
    status: LabOrderStatus
    created_at: UtcDateTime
    tests: list[LabTestStatusOut]


class LabStatusCountsOut(BaseModel):
    appointment_id: UUID
    pending: int
    ready: int


class LabPatientOut(BaseModel):
    id: UUID
    full_name: str
    phone: str
    gender: Gender | None
    age: int | None


class LabRangeOut(BaseModel):
    low: float | None
    high: float | None
    critical_low: float | None
    critical_high: float | None
    text_normal: str | None
    label: str | None


class LabPreviousOut(BaseModel):
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    flag: LabFlag | None
    released_at: UtcDateTime
    order_number: str


class LabParameterEntryOut(BaseModel):
    id: UUID
    code: str
    name: str
    unit: str | None
    value_type: LabValueType
    choices: list[str]
    decimals: int
    delta_percent: float | None
    range: LabRangeOut | None
    previous: LabPreviousOut | None
    delta_warning: bool


class LabItemDetailOut(LabItemOut):
    category: LabCategory
    sample_type: LabSampleType
    container: str | None
    parameters: list[LabParameterEntryOut]


class LabOrderDetailOut(BaseModel):
    order: LabOrderOut
    patient: LabPatientOut
    requires_verification: bool
    items: list[LabItemDetailOut]


class LabWorklistRowOut(BaseModel):
    order_id: UUID
    order_number: str
    priority: LabPriority
    status: LabOrderStatus
    created_at: UtcDateTime
    patient_id: UUID
    patient_name: str
    patient_phone: str
    patient_gender: Gender | None
    patient_age: int | None
    ordering_doctor_name: str
    counts: dict[LabItemStatus, int]
    tests: list[str]
    sample_codes: list[str]


class LabTrendPointOut(BaseModel):
    value: float
    flag: LabFlag | None
    ref_low: float | None
    ref_high: float | None
    released_at: UtcDateTime
    order_id: UUID
    order_item_id: UUID
    order_number: str


class LabTrendOut(BaseModel):
    code: str
    name: str
    unit: str | None
    points: list[LabTrendPointOut]


class LabInboxRowOut(BaseModel):
    order: LabOrderOut
    abnormal: int
    critical: int


class LabAlertOut(BaseModel):
    id: UUID
    patient_id: UUID
    patient_name: str
    order_id: UUID
    order_number: str
    parameter_name: str
    value: str
    unit: str | None
    flag: LabFlag | None
    range_label: str | None
    created_at: UtcDateTime


class LabReviewedOut(BaseModel):
    order_id: UUID
    reviewed_at: UtcDateTime


class LabRepeatOut(BaseModel):
    test_ids: list[UUID]
