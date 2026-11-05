"""The typed output of a quote."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FactorEffect:
    """One multiplier and what it did to the premium."""

    input: str  # name of the input that drove this factor
    label: str
    value: str  # the input value, as text
    factor: Decimal
    effect: Decimal  # money added (+) or removed (-) at this step
    premium_after: Decimal


@dataclass(frozen=True)
class QuoteResult:
    """Always true: base_premium + the sum of every effect == technical_premium."""

    model_version: str
    currency: str
    base_premium: Decimal
    factors: tuple[FactorEffect, ...]
    technical_premium: Decimal
    exposure_unit: str
    rate_per_exposure_unit: Decimal  # premium / exposure, 2 decimal places
    rate_on_value_pct: Decimal  # premium / value * 100, 3 decimal places
