# How a change goes live

**A change to the code or the rates cannot go live if it moves the premium on a known quote.**

The tests include 10 fixed quotes whose expected premiums were worked out by hand, separately from the rater. Every change is checked against them automatically.

```mermaid
flowchart LR
    edit["Someone changes<br/>the code or the rates"] --> tests{"93 automated tests,<br/>including 10 fixed quotes<br/>worked out by hand"}
    tests -- "any test fails, e.g. a<br/>fixed quote's premium moves" --> stop["Stopped.<br/>Nothing goes live"]
    tests -- "all pass" --> build["Builds the new<br/>Docker container"]
    build --> deploy["Azure runs<br/>the new version"]
    deploy --> health["Checks it's<br/>up and healthy"]
```

One of the fixed quotes:

| Quote | Ship | Expected premium, worked out by hand |
|---|---|---|
| modern_bulker | Bulk carrier, 30,000 GT, 3 years old | $72,535.01 |

All of this runs in GitHub Actions on every change, with nobody pressing a button.

For the technical detail, see [the architecture document](../architecture.md).
