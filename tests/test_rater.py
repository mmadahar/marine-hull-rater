import ast
import sys
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from rater import InvalidInput, load_rates, quote

TESTS = Path(__file__).parent
ROOT = TESTS.parent
RATER_FILES = sorted((ROOT / "rater").glob("*.py"))
FIXED = tomllib.loads((TESTS / "fixed_quotes.toml").read_text())["quotes"]
RATES = load_rates()
SAMPLE = FIXED[0]["inputs"]


def by_name(case):
    return case["name"]


@pytest.mark.parametrize("case", FIXED, ids=by_name)
def test_fixed_quote(case):
    result = quote(case["inputs"], RATES)
    assert result.base_premium == Decimal(case["expected_base_premium"])
    assert result.technical_premium == Decimal(case["expected_premium"])
    assert result.rate_per_exposure_unit == Decimal(case["expected_rate_per_gross_tonne"])
    assert result.rate_on_value_pct == Decimal(case["expected_rate_on_hull_value_pct"])
    assert result.exposure_unit == "gross tonne"
    assert result.model_version == "marine-hull-1.0.0"


def test_there_are_at_least_eight_fixed_quotes():
    assert len(FIXED) >= 8


@pytest.mark.parametrize("case", FIXED, ids=by_name)
def test_effects_reconcile_to_premium(case):
    result = quote(case["inputs"], RATES)
    assert result.base_premium + sum(f.effect for f in result.factors) == result.technical_premium
    assert result.factors[-1].premium_after == result.technical_premium
    assert [f.input for f in result.factors] == [
        "vessel_age", "flag_tier", "iacs_class",
        "trading_area", "deductible", "claims_count_5yr",
    ]


@pytest.mark.parametrize("case", FIXED, ids=by_name)
def test_rate_on_hull_value_is_plausible(case):
    assert Decimal("0.1") <= quote(case["inputs"], RATES).rate_on_value_pct <= Decimal("2.5")


def test_hull_value_does_not_change_premium_but_changes_rate_on_value():
    low = quote(SAMPLE | {"agreed_hull_value": 10_000_000}, RATES)
    high = quote(SAMPLE | {"agreed_hull_value": 50_000_000}, RATES)
    assert low.technical_premium == high.technical_premium
    assert low.rate_on_value_pct > high.rate_on_value_pct


def test_higher_deductible_gets_credit():
    premiums = [
        quote(SAMPLE | {"deductible": d}, RATES).technical_premium
        for d in (100_000, 150_000, 250_000, 500_000, 1_000_000)
    ]
    assert premiums == sorted(premiums, reverse=True)
    assert len(set(premiums)) == len(premiums)


def test_more_claims_cost_more():
    premiums = [
        quote(SAMPLE | {"claims_count_5yr": n}, RATES).technical_premium for n in range(7)
    ]
    assert premiums == sorted(premiums)


def test_rate_per_tonne_reduces_across_bands():
    for band_rates in RATES["base"]["rates_per_unit"].values():
        assert band_rates == sorted(band_rates, reverse=True)


def test_base_premium_has_no_jump_at_a_band_edge():
    at_edge = quote(SAMPLE | {"gross_tonnage": 20_000}, RATES).base_premium
    just_over = quote(SAMPLE | {"gross_tonnage": 20_001}, RATES).base_premium
    assert just_over - at_edge == Decimal("1.60")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vessel_type", "submarine"),
        ("iacs_class", True),
        ("gross_tonnage", 0),
        ("gross_tonnage", 300_001),
        ("gross_tonnage", "30000"),
        ("gross_tonnage", True),
        ("gross_tonnage", float("nan")),
        ("vessel_age", 3.5),
        ("vessel_age", -1),
        ("deductible", 99_999),
        ("agreed_hull_value", 0),
    ],
)
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(InvalidInput) as error:
        quote(SAMPLE | {field: value}, RATES)
    assert error.value.field == field


def test_missing_and_unknown_inputs_are_rejected():
    missing = {k: v for k, v in SAMPLE.items() if k != "flag_tier"}
    with pytest.raises(InvalidInput):
        quote(missing, RATES)
    with pytest.raises(InvalidInput):
        quote(SAMPLE | {"war_risks": "yes"}, RATES)


def test_another_class_needs_only_a_different_rates_file():
    rates = load_rates(TESTS / "other_class.toml")
    # 1000 x 4.00 + 5000 x 2.00 = 14000, x 0.90 = 12600
    result = quote({"floor_area": 6000, "construction": "timber", "sum_insured": 2_000_000}, rates)
    assert result.technical_premium == Decimal("12600.00")
    assert result.rate_on_value_pct == Decimal("0.630")


def test_inconsistent_rates_file_is_refused(tmp_path):
    text = (ROOT / "rates" / "v1.toml").read_text().replace("tier_3 = 1.20", "tier_9 = 1.20")
    path = tmp_path / "bad.toml"
    path.write_text(text)
    with pytest.raises(ValueError, match="flag_tier"):
        load_rates(path)


def test_rater_imports_only_the_standard_library_and_itself():
    for path in RATER_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            for root in roots:
                assert root == "rater" or root in sys.stdlib_module_names, f"{path}: {root}"


def test_rater_code_contains_no_marine_terms():
    for path in RATER_FILES:
        text = path.read_text().lower()
        for term in ("marine", "vessel", "hull", "tonn", "iacs", "flag", "deductible", "claims"):
            assert term not in text, f"{path}: {term}"
