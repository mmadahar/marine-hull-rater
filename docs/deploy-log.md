# Deploy log

Commands actually run, in order, on 2026-11-05 (GMT). Placeholders: `<subscription-id>`, `<tenant-id>`, `<app-id>` (app registration), `<sp-object-id>`, `<identity-principal-id>`, `<identity-resource-id>`, `<workspace-id>`, `<workspace-key>`, `<registry>` (the registry name), `<app-fqdn>`, `<account-email>`.

## 1. Prepare and register providers

| Command | Purpose |
|---|---|
| `git branch -m master main` | Rename the branch |
| `uv run pytest -q` | Baseline: 90 passed |
| `az provider register -n <p> --wait` for `Microsoft.App`, `Microsoft.OperationalInsights`, `Microsoft.ContainerRegistry`, `Microsoft.ManagedIdentity` | Register providers. All were NotRegistered. About 5 minutes in total |

## 2. Azure resources (UK South)

| Command | Purpose |
|---|---|
| `az group create -n rg-marine-hull-rater -l uksouth` | Resource group |
| `az acr create -g rg-marine-hull-rater -n <registry> --sku Basic --admin-enabled false` | Registry, no admin password |
| `az monitor log-analytics workspace create -g rg-marine-hull-rater -n log-marine-hull-rater -l uksouth --retention-time 30` | Logs |
| `az identity create -g rg-marine-hull-rater -n id-marine-hull-rater -l uksouth` | Identity the app pulls images with |
| `az role assignment create --assignee-object-id <identity-principal-id> --assignee-principal-type ServicePrincipal --role AcrPull --scope <registry-resource-id>` | Pull rights on this registry only |
| `az monitor log-analytics workspace show ... --query customerId` and `get-shared-keys ... --query primarySharedKey` | Read into shell variables for the next command; not stored |
| `az extension add --name containerapp --upgrade` | CLI extension |
| `az containerapp env create -g rg-marine-hull-rater -n cae-marine-hull-rater -l uksouth --logs-workspace-id <workspace-id> --logs-workspace-key <workspace-key>` | Environment, about 3 minutes |
| `az containerapp create -g rg-marine-hull-rater -n marine-hull-rater --environment cae-marine-hull-rater --image mcr.microsoft.com/k8se/quickstart:latest --user-assigned <identity-resource-id> --registry-server <registry>.azurecr.io --registry-identity <identity-resource-id> --ingress external --target-port 8000 --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi` | The app, with a public placeholder image until the first workflow run replaces it |

## 3. GitHub OIDC

| Command | Purpose |
|---|---|
| `az ad app create --display-name github-marine-hull-rater` | App registration, no client secret |
| `az ad sp create --id <app-id>` | Its service principal |
| `az ad app federated-credential create --id <app-id> --parameters fc.json` | Issuer `https://token.actions.githubusercontent.com`, subject first set to `repo:mmadahar/marine-hull-rater:ref:refs/heads/main` (later corrected, see Errors), audience `api://AzureADTokenExchange` |
| `az role assignment create --assignee-object-id <sp-object-id> --assignee-principal-type ServicePrincipal --role "Container Apps Contributor" --scope <resource-group-id>` | Update the app |
| same, `--role AcrPush --scope <registry-resource-id>` | Push images |
| same, `--role Reader --scope <registry-resource-id>` | `az acr login` has to read the registry resource |

## 4. Budget

| Command | Purpose |
|---|---|
| `az rest --method put --url https://management.azure.com/subscriptions/<subscription-id>/providers/Microsoft.Consumption/budgets/budget-monthly-20?api-version=2023-11-01 --body @budget.json` | Monthly budget of 20, alerts at 50, 80 and 100 percent actual and 100 percent forecast, to `<account-email>` from `az account show --query user.name`. `budget.json` was kept outside the repo |

`az rest` is used because `az consumption budget create` can't set notifications.

## 5. Repo and secrets

| Command | Purpose |
|---|---|
| `gh repo create mmadahar/marine-hull-rater --private --source . --remote origin` | Private repo |
| `gh secret set AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | IDs for `azure/login` |
| `gh variable set ACR_NAME` | Registry name |
| `git add`, `git commit`, `git push -u origin main` | First push, which starts the workflow |

## Errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `az provider register ... --wait` ran past the 3-minute shell limit | Registration is slow | Left it running in the background |
| Cost Management query: `429 Too many requests` | Throttled just after registration | Retried once, see next row |
| Cost Management query retry: `NotFound ... doesn't have valid WebDirect/AIRS offer type` | Not available on this new subscription yet | `az billing account list` then `az billing profile list --account-name <billing-account>`: currency GBP, so the budget of 20 is £20 |
| `az consumption budget list` (preview): `429`; later usageDetails: `400 Billing Period is not supported` | Throttling; API needs date filters on this offer | Listed budgets through `az rest` instead: none existed |
| First workflow run, `azure/login`: `AADSTS700213: No matching federated identity record` for subject `repo:mmadahar@<owner-github-id>/marine-hull-rater@<repo-github-id>:ref:refs/heads/main` | GitHub now issues subjects containing the numeric owner and repo IDs, so the `repo:owner/name:...` form didn't match | `az ad app federated-credential update --id <app-id> --federated-credential-id github-main-push --parameters '{...subject as presented...}'`, then `gh run rerun <run-id> --failed`, which succeeded. Read the exact subject from the failed login log |
| `az extension add --name containerapp --upgrade`: `Pip failed with status code 1` | Upgrade of the installed extension failed locally | Not blocking: the installed version worked. CI installs its own |
| First live quote after a successful run returned the previous commit | `az containerapp update` returns before traffic moves to the new revision; the workflow's health check passed against the old one. Traffic had moved a minute later | Workflow now waits for `latestReadyRevisionName` to equal `latestRevisionName` before checking `/health` |
| `az monitor log-analytics query`: `Pip failed with status code 1` | The CLI couldn't install its preview extension | Queried with `az rest --method post --url https://api.loganalytics.io/v1/workspaces/<workspace-id>/query --resource https://api.loganalytics.io --body '{"query":"..."}'` |
| Health-check step failed with exit code 1 although the app was deployed and healthy | `read` returns non-zero with no trailing newline, and the step runs with `bash -e` | Read the values with `sed -n` from a variable instead |

## 6. Live checks

| Command | Purpose |
|---|---|
| `curl -X POST https://<app-fqdn>/quote -H 'content-type: application/json' -d @q.json`, plus `GET /` and `GET /health` | Fixed quote, page and health |
| 31 quotes with `X-Forwarded-For: 198.51.100.$i` | One varying fake value: 30 × 200 then 429 |
| 31 quotes with `X-Forwarded-For: 10.0.0.$i, 198.51.100.$i` | Varying fake list: 30 × 200 then 429 |
| 31 quotes with two `X-Forwarded-For` header lines, both varying | Same, as separate lines |
| Repeated local quotes for over 2 minutes, while a temporary `rate-limit-probe` branch (holding only `probe.yml`, so no deploy) ran 31 quotes from a GitHub runner; then `git push origin --delete rate-limit-probe` | The runner got 30 × 200 then 429 while the local address was getting 429s: separate limits for separate addresses. `app/rate_limit.py` needed no change |
| `az containerapp logs show -g rg-marine-hull-rater -n marine-hull-rater --tail 200 --format text`, grep the quote ID | Quote log line |
| `az rest --method post --url https://api.loganalytics.io/v1/workspaces/<workspace-id>/query --resource https://api.loganalytics.io --body '{"query":"ContainerAppConsoleLogs_CL \| where Log_s has '<quote-id>'"}'` | Same line in Log Analytics, about 3 minutes later at most |
| Added `tests/test_gate.py` with `assert False`, committed, pushed; `gh run view <run-id>` | Gate test: `test` failed, `deploy` skipped, live commit unchanged |
| `git revert`, pushed | Gate test revert: deployed, live commit moved to the revert, `/health` OK |
| `az containerapp replica list -g rg-marine-hull-rater -n marine-hull-rater --revision <revision>`, every 30 seconds | Reached 0 replicas (`ScaledToZero`) about 6 minutes after the last request |
| `curl -w '%{time_total}' https://<app-fqdn>/health` | Cold start 21.2 seconds, warm 0.08 seconds |

## 7. Daily log cap

| Command | Purpose |
|---|---|
| `az monitor log-analytics workspace update -g rg-marine-hull-rater -n log-marine-hull-rater --quota 0.2` | Caps log ingestion at 0.2 GB a day, so heavy traffic can't run up log charges. If the cap is hit, new log lines, including audit lines, are dropped until the daily reset. |
