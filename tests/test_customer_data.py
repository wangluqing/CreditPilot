"""Offline tests for the frozen synthetic customer data contract."""

import hashlib
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from creditpilot.models.customer import (
    DATA_VERSION,
    GENERATOR_SEED,
    SCHEMA_VERSION,
    CustomerRecord,
    SyntheticDataset,
)
from creditpilot.tools.customer import (
    AnalysisStatus,
    CustomerErrorCode,
    CustomerTool,
    EvidenceStatus,
)
from creditpilot.tools.synthetic import canonical_json, generate_dataset

DATA_FILE = Path(__file__).parents[1] / "data" / "synthetic" / "customers_v1.json"


@pytest.fixture(scope="module")
def dataset() -> SyntheticDataset:
    return SyntheticDataset.model_validate_json(DATA_FILE.read_text(encoding="utf-8"))


def test_generated_dataset_has_frozen_metadata_and_at_least_30_records(
    dataset: SyntheticDataset,
) -> None:
    assert dataset.manifest.data_version == DATA_VERSION
    assert dataset.manifest.schema_version == SCHEMA_VERSION
    assert dataset.manifest.generator_seed == GENERATOR_SEED
    assert dataset.manifest.record_count == len(dataset.customers)
    assert len(dataset.customers) >= 30


def test_customer_ids_are_unique_and_exactly_formatted(
    dataset: SyntheticDataset,
) -> None:
    customer_ids = [customer.customer_id for customer in dataset.customers]
    assert len(customer_ids) == len(set(customer_ids))
    assert customer_ids == [f"DEMO-{number:04d}" for number in range(1, 31)]


def test_generation_is_reproducible() -> None:
    first = canonical_json(generate_dataset(seed=GENERATOR_SEED))
    second = canonical_json(generate_dataset(seed=GENERATOR_SEED))
    checked_in = DATA_FILE.read_text(encoding="utf-8")

    assert first == second == checked_in
    assert hashlib.sha256(first.encode()).digest() == hashlib.sha256(
        second.encode()
    ).digest()


def test_customer_fields_have_strict_types_and_ranges(
    dataset: SyntheticDataset,
) -> None:
    for customer in dataset.customers:
        assert type(customer.monthly_income) is int
        assert type(customer.verified_identity) is bool
        assert 1_000 <= customer.monthly_income <= 100_000
        assert 0 <= customer.monthly_debt_payment <= 100_000
        assert 0 <= customer.employment_months <= 600
        assert 0 <= customer.credit_history_months <= 600
        assert 0 <= customer.delinquency_count_12m <= 12
        assert 0 <= customer.inquiry_count_6m <= 20
        assert 1_000 <= customer.requested_amount <= 500_000


@pytest.mark.parametrize("bad_income", [0, -1, "5000", None])
def test_invalid_income_is_rejected_without_coercion(bad_income: object) -> None:
    raw = generate_dataset().customers[0].model_dump()
    raw["monthly_income"] = bad_income

    with pytest.raises(ValidationError):
        CustomerRecord.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("monthly_debt_payment", "100"),
        ("employment_months", "12"),
        ("credit_history_months", "24"),
        ("delinquency_count_12m", "0"),
        ("inquiry_count_6m", "1"),
        ("requested_amount", "1000"),
        ("verified_identity", 1),
    ],
)
def test_all_numeric_and_boolean_fields_reject_implicit_conversion(
    field: str,
    bad_value: object,
) -> None:
    raw = generate_dataset().customers[0].model_dump()
    raw[field] = bad_value

    with pytest.raises(ValidationError):
        CustomerRecord.model_validate(raw)


def test_dataset_contains_boundary_and_display_optional_examples(
    dataset: SyntheticDataset,
) -> None:
    assert any(
        customer.monthly_debt_payment * 100 == customer.monthly_income * 80
        for customer in dataset.customers
    )
    assert any(
        customer.requested_amount == 12 * customer.monthly_income
        for customer in dataset.customers
    )
    assert any(customer.synthetic_region is None for customer in dataset.customers)


def test_customer_tool_returns_exact_snapshot_and_pending_evidence(
    dataset: SyntheticDataset,
) -> None:
    tool = CustomerTool.from_dataset(dataset)
    result = tool.lookup("DEMO-0001")

    assert result.analysis_status is AnalysisStatus.SUCCESS
    assert result.customer == dataset.customers[0]
    assert result.data_version == DATA_VERSION
    assert result.missing_required_fields == ()
    assert all(result.field_availability.values())
    assert len(result.evidence) == 12
    assert {item.field_path for item in result.evidence} == {
        f"/{field}" for field in CustomerRecord.model_fields
    }
    assert all(
        item.validation_status is EvidenceStatus.PENDING for item in result.evidence
    )


def test_customer_tool_loads_checked_in_default_dataset() -> None:
    result = CustomerTool.from_default_dataset().lookup("DEMO-0001")

    assert result.analysis_status is AnalysisStatus.SUCCESS
    assert result.customer is not None
    assert result.customer.customer_id == "DEMO-0001"


def test_customer_tool_does_not_fuzzy_match_or_create_customer(
    dataset: SyntheticDataset,
) -> None:
    tool = CustomerTool.from_dataset(dataset)
    result = tool.lookup("DEMO-9999")

    assert result.analysis_status is AnalysisStatus.NOT_FOUND
    assert result.customer is None
    assert result.errors[0].code is CustomerErrorCode.CUSTOMER_NOT_FOUND
    assert result.evidence == ()


@pytest.mark.parametrize(
    "customer_id",
    ["demo-0001", "DEMO-001", "DEMO-00001", "DEMO-ABCD", "../DEMO-0001", 1, None],
)
def test_customer_tool_rejects_invalid_customer_id(customer_id: object) -> None:
    tool = CustomerTool.from_dataset(generate_dataset())
    result = tool.lookup(customer_id)

    assert result.analysis_status is AnalysisStatus.INVALID_INPUT
    assert result.customer is None
    assert result.errors[0].code is CustomerErrorCode.INVALID_CUSTOMER_ID


def test_missing_required_field_is_partial_and_never_filled() -> None:
    raw = generate_dataset().customers[0].model_dump()
    del raw["monthly_income"]
    tool = CustomerTool([raw])

    result = tool.lookup("DEMO-0001")

    assert result.analysis_status is AnalysisStatus.PARTIAL
    assert result.customer is None
    assert result.missing_required_fields == ("monthly_income",)
    assert result.field_availability["monthly_income"] is False
    assert result.errors[0].code is CustomerErrorCode.REQUIRED_FIELD_MISSING


def test_missing_optional_field_is_reported_without_fabricated_evidence() -> None:
    raw = generate_dataset().customers[0].model_dump()
    del raw["scenario_label"]
    tool = CustomerTool([raw])

    result = tool.lookup("DEMO-0001")

    assert result.analysis_status is AnalysisStatus.SUCCESS
    assert result.missing_optional_fields == ("scenario_label",)
    assert result.field_availability["scenario_label"] is False
    assert "/scenario_label" not in {item.field_path for item in result.evidence}


def test_customer_tool_rejects_unsupported_expected_data_version() -> None:
    tool = CustomerTool.from_dataset(generate_dataset())

    result = tool.lookup("DEMO-0001", expected_data_version="synthetic-v2")

    assert result.analysis_status is AnalysisStatus.FAILED
    assert result.customer is None
    assert result.errors[0].code is CustomerErrorCode.DATA_VERSION_MISMATCH


@pytest.mark.parametrize("bad_income", [0, -1, "5000"])
def test_customer_tool_fails_closed_for_invalid_income(bad_income: object) -> None:
    raw = generate_dataset().customers[0].model_dump()
    raw["monthly_income"] = bad_income
    tool = CustomerTool([raw])

    result = tool.lookup("DEMO-0001")

    assert result.analysis_status is AnalysisStatus.FAILED
    assert result.customer is None
    assert result.errors[0].code is CustomerErrorCode.DATA_CONTRACT_VIOLATION


def test_customer_tool_has_no_network_or_downstream_side_effects(
    dataset: SyntheticDataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    tool = CustomerTool.from_dataset(dataset)

    assert tool.lookup("DEMO-0001").analysis_status is AnalysisStatus.SUCCESS
    assert not hasattr(tool, "rule_engine")
    assert not hasattr(tool, "risk_model")
    assert not hasattr(tool, "decision_tool")


def test_checked_in_json_contains_no_real_world_identifiers() -> None:
    text = DATA_FILE.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert "phone" not in text.lower()
    assert "address" not in text.lower()
    assert "identity_number" not in text.lower()
    assert set(payload) == {"manifest", "customers"}
