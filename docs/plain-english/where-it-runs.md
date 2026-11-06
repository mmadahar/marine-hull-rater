# Where it runs

```mermaid
flowchart TB
    u["Underwriter's browser"]
    subgraph azure ["Microsoft Azure, UK South"]
        subgraph aca ["Azure Container Apps"]
            app["The rater<br/>(Docker container)<br/>sleeps when idle,<br/>wakes in about 20 seconds"]
        end
        reg["Private registry<br/>stores each version<br/>of the container"]
        logs["Log Analytics<br/>keeps the audit records"]
    end
    gh["GitHub Actions"]

    u -- "HTTPS" --> app
    gh -- "uploads new version" --> reg
    reg -- "app pulls it" --> app
    app -- "one record per quote" --> logs
```

| Part | What it does, in plain English |
|---|---|
| Azure Container Apps | Runs the rater. It switches off when nobody is using it, so it costs almost nothing, and the first visit wakes it in about 20 seconds. |
| Docker container | The app and its rates packed into one sealed box, so it runs exactly the same on a laptop as on Azure. |
| Private registry | A store of every version of that box. Azure runs the latest one. |
| Log Analytics | Where every quote's audit record is kept, for 30 days. |

For the technical detail, see [the architecture document](../architecture.md).
