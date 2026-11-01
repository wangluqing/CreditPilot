"""Deterministic generator for CreditPilot's original synthetic dataset."""

import json
import random
from pathlib import Path
from typing import Any

from creditpilot.models.customer import (
    DATA_VERSION,
    GENERATOR_SEED,
    SCHEMA_VERSION,
    CustomerRecord,
    SyntheticDataset,
    SyntheticDatasetManifest,
)

REGIONS = ("SYN-NORTH", "SYN-SOUTH", "SYN-EAST", "SYN-WEST")

# Hand-authored boundary profiles are synthetic and deliberately cover the
# frozen demo rules without encoding any real institution's policy data.
BOUNDARY_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "verified_identity": True,
        "monthly_income": 10_000,
        "monthly_debt_payment": 2_000,
        "employment_months": 120,
        "credit_history_months": 240,
        "delinquency_count_12m": 0,
        "inquiry_count_6m": 0,
        "requested_amount": 12_000,
        "scenario_label": "complete-low-burden",
    },
    {
        "verified_identity": False,
        "monthly_income": 8_000,
        "monthly_debt_payment": 1_000,
        "employment_months": 90,
        "credit_history_months": 180,
        "delinquency_count_12m": 0,
        "inquiry_count_6m": 1,
        "requested_amount": 10_000,
        "scenario_label": "identity-boundary",
    },
    {
        "verified_identity": True,
        "monthly_income": 8_000,
        "monthly_debt_payment": 1_000,
        "employment_months": 90,
        "credit_history_months": 180,
        "delinquency_count_12m": 3,
        "inquiry_count_6m": 1,
        "requested_amount": 10_000,
        "scenario_label": "delinquency-equal-boundary",
    },
    {
        "verified_identity": True,
        "monthly_income": 5_000,
        "monthly_debt_payment": 4_000,
        "employment_months": 60,
        "credit_history_months": 120,
        "delinquency_count_12m": 0,
        "inquiry_count_6m": 2,
        "requested_amount": 20_000,
        "scenario_label": "debt-ratio-equal-boundary",
    },
    {
        "verified_identity": True,
        "monthly_income": 5_000,
        "monthly_debt_payment": 1_500,
        "employment_months": 60,
        "credit_history_months": 120,
        "delinquency_count_12m": 0,
        "inquiry_count_6m": 2,
        "requested_amount": 60_000,
        "scenario_label": "request-ratio-equal-boundary",
    },
    {
        "verified_identity": True,
        "monthly_income": 5_000,
        "monthly_debt_payment": 1_500,
        "employment_months": 60,
        "credit_history_months": 120,
        "delinquency_count_12m": 0,
        "inquiry_count_6m": 2,
        "requested_amount": 60_001,
        "scenario_label": "request-ratio-above-boundary",
    },
)


def _random_profile(rng: random.Random, index: int) -> dict[str, Any]:
    income = rng.randrange(2_000, 20_001, 500)
    debt_ratio_percent = (index * 17) % 101
    annual_income = 12 * income
    request_ratio_percent = (index * 23) % 141
    return {
        "verified_identity": index % 9 != 0,
        "monthly_income": income,
        "monthly_debt_payment": income * debt_ratio_percent // 100,
        "employment_months": rng.randint(0, 180),
        "credit_history_months": rng.randint(0, 300),
        "delinquency_count_12m": index % 6,
        "inquiry_count_6m": rng.randint(0, 12),
        "requested_amount": max(
            1_000,
            min(500_000, annual_income * request_ratio_percent // 100),
        ),
        "scenario_label": f"generated-scenario-{index:02d}",
    }


def generate_dataset(
    *,
    count: int = 30,
    seed: int = GENERATOR_SEED,
) -> SyntheticDataset:
    """Generate a reproducible, valid synthetic dataset without external data."""
    if count < 30:
        raise ValueError("count must be at least 30")

    rng = random.Random(seed)
    customers: list[CustomerRecord] = []
    for offset in range(count):
        number = offset + 1
        profile = (
            dict(BOUNDARY_PROFILES[offset])
            if offset < len(BOUNDARY_PROFILES)
            else _random_profile(rng, number)
        )
        profile.update(
            customer_id=f"DEMO-{number:04d}",
            data_version=DATA_VERSION,
            synthetic_region=REGIONS[offset % len(REGIONS)] if offset % 7 else None,
        )
        customers.append(CustomerRecord.model_validate(profile))

    manifest = SyntheticDatasetManifest(
        data_version=DATA_VERSION,
        schema_version=SCHEMA_VERSION,
        generator_seed=seed,
        record_count=count,
    )
    return SyntheticDataset(manifest=manifest, customers=tuple(customers))


def canonical_json(dataset: SyntheticDataset) -> str:
    """Serialize a dataset using stable UTF-8 JSON formatting."""
    payload = dataset.model_dump(mode="json")
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        separators=(",", ": "),
    ) + "\n"


def write_dataset(path: Path, dataset: SyntheticDataset) -> None:
    """Write a generated dataset to an explicitly supplied local path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(dataset), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[3]
    write_dataset(
        project_root / "data" / "synthetic" / "customers_v1.json",
        generate_dataset(),
    )
