import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rate_limit import RateLimiter
from rater import load_rates

FIXED_QUOTES = tomllib.loads(
    (Path(__file__).parent / "fixed_quotes.toml").read_text()
)["quotes"]
FIXED = FIXED_QUOTES[0]
VALID = FIXED["inputs"]


@pytest.fixture
def client():
    return TestClient(create_app())


def errors_for(client, **changes):
    response = client.post("/quote", json={**VALID, **changes})
    assert response.status_code == 422
    return {error["field"]: error["message"] for error in response.json()["errors"]}


# ---- Quotes ----


def test_quote_matches_a_fixed_quote(client):
    response = client.post("/quote", json=VALID)

    assert response.status_code == 200
    body = response.json()
    assert body["base_premium"] == FIXED["expected_base_premium"]
    assert body["technical_premium"] == FIXED["expected_premium"]
    assert body["rate_per_gross_tonne"] == FIXED["expected_rate_per_gross_tonne"]
    assert body["rate_on_hull_value_pct"] == FIXED["expected_rate_on_hull_value_pct"]
    assert body["currency"] == "USD"
    assert body["exposure_unit"] == "gross tonne"
    assert body["model_version"] == "marine-hull-1.0.0"
    assert body["quote_id"]
    assert set(body["factors"][0]) == {
        "input", "label", "value", "factor", "effect", "premium_after",
    }


def test_git_commit_comes_from_the_environment(monkeypatch):
    assert TestClient(create_app()).post("/quote", json=VALID).json()["git_commit"] == "local"
    monkeypatch.setenv("GIT_COMMIT", "abc123")
    assert TestClient(create_app()).post("/quote", json=VALID).json()["git_commit"] == "abc123"


# ---- Validation ----


@pytest.mark.parametrize(
    "field, bad",
    [
        ("vessel_type", "submarine"),
        ("vessel_type", 1),
        ("iacs_class", True),
        ("gross_tonnage", 99),
        ("gross_tonnage", 300001),
        ("gross_tonnage", "30000"),
        ("gross_tonnage", True),
        ("gross_tonnage", None),
        ("vessel_age", 2.5),
        ("vessel_age", "3"),
        ("vessel_age", -1),
        ("vessel_age", True),
    ],
)
def test_bad_values_are_named_by_field(client, field, bad):
    assert list(errors_for(client, **{field: bad})) == [field]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_rejected(client, literal):
    # json.dumps won't write these, but Python's JSON parser accepts them.
    text = json.dumps(VALID).replace("30000", literal, 1)
    response = client.post("/quote", content=text, headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "gross_tonnage"


def test_unknown_field_is_rejected(client):
    assert list(errors_for(client, discount=10)) == ["discount"]


def test_missing_field_is_rejected(client):
    inputs = {name: value for name, value in VALID.items() if name != "flag_tier"}
    response = client.post("/quote", json=inputs)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "flag_tier"


def test_every_bad_field_is_reported(client):
    assert set(errors_for(client, vessel_type="x", vessel_age=-1)) == {"vessel_type", "vessel_age"}


def test_malformed_json_is_a_422(client):
    response = client.post("/quote", content="{not json", headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body"


@pytest.mark.parametrize("hull_value", [150000, 149999])
def test_deductible_must_be_below_hull_value(client, hull_value):
    # The fixed quote's deductible is 150000.
    errors = errors_for(client, agreed_hull_value=hull_value)
    assert list(errors) == ["deductible"]


def test_bounds_come_from_the_rates_file(client):
    definition = load_rates()["inputs"]["gross_tonnage"]
    assert client.post("/quote", json={**VALID, "gross_tonnage": definition["max"]}).status_code == 200
    errors_for(client, gross_tonnage=definition["max"] + 1)


# ---- Rate limiting ----


def test_31st_quote_in_a_minute_is_refused(client):
    for _ in range(30):
        assert client.post("/quote", json=VALID).status_code == 200
    response = client.post("/quote", json=VALID)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_bad_requests_count_towards_the_limit(client):
    for _ in range(30):
        client.post("/quote", content="{not json")
    assert client.post("/quote", json=VALID).status_code == 429


def test_other_routes_are_not_limited(client):
    for _ in range(31):
        assert client.get("/health").status_code == 200


def test_changing_the_spoofable_part_of_the_header_does_not_help(client):
    for attempt in range(30):
        headers = {"x-forwarded-for": f"10.0.0.{attempt}, 203.0.113.9"}
        assert client.post("/quote", json=VALID, headers=headers).status_code == 200
    headers = {"x-forwarded-for": "10.9.9.9, 203.0.113.9"}
    assert client.post("/quote", json=VALID, headers=headers).status_code == 429


def test_a_spoofed_header_sent_as_a_separate_line_does_not_help(client):
    for attempt in range(30):
        headers = [("x-forwarded-for", f"10.0.0.{attempt}"), ("x-forwarded-for", "203.0.113.9")]
        assert client.post("/quote", json=VALID, headers=headers).status_code == 200
    headers = [("x-forwarded-for", "10.9.9.9"), ("x-forwarded-for", "203.0.113.9")]
    assert client.post("/quote", json=VALID, headers=headers).status_code == 429


def test_clients_seen_by_the_ingress_are_limited_separately(client):
    for _ in range(30):
        client.post("/quote", json=VALID, headers={"x-forwarded-for": "203.0.113.9"})
    other = client.post("/quote", json=VALID, headers={"x-forwarded-for": "203.0.113.10"})
    assert other.status_code == 200


def test_hits_expire_after_the_window():
    now = [0.0]
    limiter = RateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    now[0] = 60.0
    assert limiter.allow("a")


def test_memory_is_bounded():
    limiter = RateLimiter(limit=2, max_clients=3)
    for number in range(100):
        limiter.allow(f"client-{number}")
    assert list(limiter.hits) == ["client-97", "client-98", "client-99"]


# ---- Audit log ----


def test_a_quote_logs_one_json_line(client, capsys):
    capsys.readouterr()
    body = client.post("/quote", json=VALID).json()

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["quote_id"] == body["quote_id"]
    assert logged["model_version"] == body["model_version"]
    assert logged["git_commit"] == body["git_commit"]
    assert logged["inputs"]["vessel_type"] == "bulk_carrier"
    assert logged["inputs"]["gross_tonnage"] == "30000"
    assert logged["outputs"]["technical_premium"] == FIXED["expected_premium"]
    assert logged["outputs"]["factors"] == body["factors"]


def test_a_refused_quote_logs_nothing(client, capsys):
    capsys.readouterr()
    errors_for(client, vessel_type="submarine")
    assert capsys.readouterr().out == ""


# ---- Other routes ----


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_options_come_from_the_rates_file(client):
    inputs = load_rates()["inputs"]
    body = client.get("/options").json()
    assert body["inputs"]["vessel_type"]["options"] == inputs["vessel_type"]["options"]
    assert body["inputs"]["gross_tonnage"]["min"] == inputs["gross_tonnage"]["min"]
    assert body["inputs"]["gross_tonnage"]["max"] == inputs["gross_tonnage"]["max"]
    assert set(body["inputs"]) == set(inputs)


def test_static_files_are_served_when_present(tmp_path):
    (tmp_path / "index.html").write_text("hello")
    client = TestClient(create_app(static_dir=tmp_path))
    assert client.get("/").text == "hello"
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_static_folder_is_not_an_error(tmp_path):
    client = TestClient(create_app(static_dir=tmp_path / "absent"))
    assert client.get("/").status_code == 404
