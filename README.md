# Marine hull rater

A small FastAPI service and web page that prices a marine hull risk from a rates file. Each quote shows how every factor moved the premium, and writes one JSON line to stdout as an audit trail.

**All rates in this project are made up. They are illustrative, are not based on any real pricing, and must not be used to price real risks.**

See [the architecture document](docs/architecture.md) for how it is built and why.

See [the from-scratch guide](docs/from-scratch.md) to build, deploy and tear it down yourself.

## Run it locally

Needs [uv](https://docs.astral.sh/uv/) and Python 3.14.

```sh
uv run pytest
uv run uvicorn app.main:app --reload --port 8000
```

Then open <http://localhost:8000>. Or use Docker:

```sh
docker build --build-arg GIT_COMMIT="$(git rev-parse HEAD)" -t marine-hull-rater .
docker run --rm -p 8000:8000 marine-hull-rater
```

## Notes

- The rating logic could also run on Azure Functions.
- Marine hull is the worked example; the structure can be reused for other classes of business.

## Next steps

- Draft and approval workflows
- Logins
- Version comparison
- A database

## Teardown

Deleting the resource group removes the app, environment, registry, identity and logs. The budget and app registration sit outside it. Find the app ID with `az ad app list --display-name github-marine-hull-rater --query "[].appId" -o tsv`.

```sh
az group delete --name rg-marine-hull-rater
az rest --method delete --url "https://management.azure.com/subscriptions/<subscription-id>/providers/Microsoft.Consumption/budgets/budget-monthly-20?api-version=2023-11-01"
az ad app delete --id <app-id>
gh repo delete mmadahar/marine-hull-rater
```
