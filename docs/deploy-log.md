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
| `az ad app federated-credential create --id <app-id> --parameters fc.json` | Issuer `https://token.actions.githubusercontent.com`, subject `repo:mmadahar/marine-hull-rater:ref:refs/heads/main`, audience `api://AzureADTokenExchange` |
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
| Cost Management query retry: `NotFound ... doesn't have valid WebDirect/AIRS offer type` | Not available on this new subscription yet | Took the currency from the billing profile instead |
| `az consumption budget list` (preview): `429`; later usageDetails: `400 Billing Period is not supported` | Throttling; API needs date filters on this offer | Listed budgets through `az rest` instead: none existed |
| `az extension add --name containerapp --upgrade`: `Pip failed with status code 1` | Upgrade of the installed extension failed locally | Not blocking: the installed version worked. CI installs its own |
