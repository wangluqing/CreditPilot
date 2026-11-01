"""Strict data contracts for original synthetic customer records."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from pydantic.types import StringConstraints

DATA_VERSION = "synthetic-v1"
SCHEMA_VERSION = "customer-schema-v1"
GENERATOR_SEED = 202501

CustomerId = Annotated[
    str,
    StringConstraints(pattern=r"^DEMO-[0-9]{4}$", strict=True),
]
ScenarioLabel = Annotated[str, StringConstraints(max_length=40, strict=True)]


class CustomerRecord(BaseModel):
    """A frozen, strict synthetic customer snapshot with exactly 12 fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    customer_id: CustomerId
    data_version: Literal["synthetic-v1"]
    verified_identity: StrictBool
    monthly_income: StrictInt = Field(ge=1_000, le=100_000)
    monthly_debt_payment: StrictInt = Field(ge=0, le=100_000)
    employment_months: StrictInt = Field(ge=0, le=600)
    credit_history_months: StrictInt = Field(ge=0, le=600)
    delinquency_count_12m: StrictInt = Field(ge=0, le=12)
    inquiry_count_6m: StrictInt = Field(ge=0, le=20)
    requested_amount: StrictInt = Field(ge=1_000, le=500_000)
    synthetic_region: Literal[
        "SYN-NORTH",
        "SYN-SOUTH",
        "SYN-EAST",
        "SYN-WEST",
    ] | None = None
    scenario_label: ScenarioLabel | None = None


class SyntheticDatasetManifest(BaseModel):
    """Metadata required to reproduce and validate a synthetic dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    data_version: Literal["synthetic-v1"]
    schema_version: Literal["customer-schema-v1"]
    generator_seed: StrictInt
    record_count: StrictInt = Field(ge=30)


class SyntheticDataset(BaseModel):
    """A versioned collection of valid synthetic customer records."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    manifest: SyntheticDatasetManifest
    customers: tuple[CustomerRecord, ...]

