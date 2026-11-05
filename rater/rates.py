"""Load a rates file and check it is consistent. Numbers load as exact Decimals."""

import tomllib
from decimal import Decimal
from pathlib import Path

DEFAULT_RATES = Path(__file__).parent.parent / "rates" / "v1.toml"


def load_rates(path: Path | str = DEFAULT_RATES) -> dict:
    with open(path, "rb") as file:
        rates = tomllib.load(file, parse_float=Decimal)
    _check(rates)
    return rates


def _check(rates: dict) -> None:
    inputs, base = rates["inputs"], rates["base"]

    _require(
        set(base["rates_per_unit"]) == set(inputs[base["segment_input"]]["options"]),
        "base rates must cover exactly the segment options",
    )
    for segment, band_rates in base["rates_per_unit"].items():
        _require(
            len(band_rates) == len(base["band_from"]),
            f"{segment}: needs one rate per band",
        )
    _check_ascending(base["band_from"], 0, "base bands")

    for factor in rates["factors"]:
        definition = inputs[factor["input"]]
        if "table" in factor:
            _require(
                set(factor["table"]) == set(definition["options"]),
                f"{factor['input']}: table must cover exactly the options",
            )
        else:
            starts = [band["from"] for band in factor["bands"]]
            _check_ascending(starts, definition["min"], f"{factor['input']} bands")


def _check_ascending(starts: list, lowest_input: Decimal, name: str) -> None:
    _require(starts == sorted(set(starts)), f"{name} must ascend")
    _require(starts[0] <= lowest_input, f"{name} must cover the lowest valid input")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid rates file: {message}")
