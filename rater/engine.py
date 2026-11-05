"""Turn validated inputs into a quote. Everything specific to a class is in the rates file."""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from rater.result import FactorEffect, QuoteResult

CENTS = Decimal("0.01")
THREE_PLACES = Decimal("0.001")


class InvalidInput(ValueError):
    """An input is missing, unknown or out of range. `field` names which one."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field


def quote(inputs: Mapping, rates: dict) -> QuoteResult:
    clean = _validate(inputs, rates["inputs"])
    base = rates["base"]

    # 1. Base premium from exposure and segment.
    exposure = clean[base["exposure_input"]]
    band_rates = base["rates_per_unit"][clean[base["segment_input"]]]
    premium = _banded_amount(exposure, base["band_from"], band_rates)
    base_premium = _money(premium)

    # 2. Apply each multiplier in file order. Effects are differences between
    #    rounded running totals, so they add up to the premium exactly.
    effects = []
    previous = base_premium
    for spec in rates["factors"]:
        value = clean[spec["input"]]
        factor = _factor_for(spec, value)
        premium *= factor
        current = _money(premium)
        effects.append(
            FactorEffect(
                input=spec["input"],
                label=rates["inputs"][spec["input"]]["label"],
                value=str(value),
                factor=factor,
                effect=current - previous,
                premium_after=current,
            )
        )
        previous = current

    # 3. Sense-check rates, from the rounded premium. The value is only divided into it.
    value_at_risk = clean[rates["sense_check"]["value_input"]]
    rate_on_value = (previous / value_at_risk * 100).quantize(THREE_PLACES, ROUND_HALF_UP)
    refer_above = rates["sense_check"].get("refer_above_pct")
    return QuoteResult(
        model_version=rates["model"]["version"],
        currency=rates["model"]["currency"],
        base_premium=base_premium,
        factors=tuple(effects),
        technical_premium=previous,
        exposure_unit=base["exposure_unit"],
        rate_per_exposure_unit=_money(previous / exposure),
        rate_on_value_pct=rate_on_value,
        refer_to_underwriter=refer_above is not None and rate_on_value > refer_above,
    )


def _banded_amount(exposure: Decimal, band_from: list, band_rates: list) -> Decimal:
    """Charge each slice of the exposure at its own band's rate."""
    total = Decimal(0)
    band_to = [*band_from[1:], exposure]
    for start, end, rate in zip(band_from, band_to, band_rates):
        total += max(min(exposure, end) - start, 0) * rate
    return total


def _factor_for(spec: dict, value) -> Decimal:
    if "table" in spec:
        return spec["table"][value]
    # The highest band whose start the value has reached.
    return [band for band in spec["bands"] if value >= band["from"]][-1]["factor"]


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, ROUND_HALF_UP)


def _validate(inputs: Mapping, definitions: dict) -> dict:
    for name in inputs:
        if name not in definitions:
            raise InvalidInput(name, "unknown input")
    clean = {}
    for name, definition in definitions.items():
        if name not in inputs:
            raise InvalidInput(name, "is required")
        clean[name] = _validate_one(name, inputs[name], definition)
    return clean


def _validate_one(name: str, value, definition: dict):
    if definition["type"] == "choice":
        if value not in definition["options"]:
            raise InvalidInput(name, f"must be one of {definition['options']}")
        return value

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise InvalidInput(name, "must be a number")
    number = Decimal(str(value))
    if not number.is_finite():
        raise InvalidInput(name, "must be a finite number")
    if definition["type"] == "integer" and number != number.to_integral_value():
        raise InvalidInput(name, "must be a whole number")
    if not definition["min"] <= number <= definition["max"]:
        raise InvalidInput(
            name, f"must be between {definition['min']} and {definition['max']}"
        )
    return number
