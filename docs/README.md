# csmarket documentation

This folder is the project's living documentation. **Update it in the same change as the code
you touch** — `AGENTS.md` § 5 lists which change needs which doc.

## Sections

| Folder                             | What lives here                                                                              |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| [`architecture/`](./architecture/) | System overview (C4 context), module map, sequence diagrams, Redis cache keys                |
| [`decisions/`](./decisions/)       | Architecture Decision Records (ADRs), numbered, MADR template                                |
| [`runbooks/`](./runbooks/)         | Operational procedures: deploys, admin bootstrap, kassas, wallet, orders, Waxpeer, incidents |
| [`api/`](./api/)                   | Generated OpenAPI schema (`openapi.json`) + auth / idempotency / limits notes                |
| [`onboarding/`](./onboarding/)     | Local setup                                                                                  |
| [`security/`](./security/)         | PII inventory and handling rules                                                             |
| [`superpowers/`](./superpowers/)   | Specs and plans; the design spec is the source of truth                                      |

[`product/flows/`](./product/flows/) holds user-facing flows with Mermaid diagrams (sign-in, trade link, browse, top-up, buy).

## Conventions

- Diagrams in **Mermaid** — inline in the markdown, or as `.mmd` files beside it.
- ADRs use the **MADR** template at `decisions/0000-template.md`. Numbering is strictly
  sequential; an ADR is never deleted, only superseded.
- Every Redis key is catalogued in `architecture/cache-keys.md` (one row per key: TTL,
  writer, reader, PII).
- Runbooks that a Prometheus alert links to (`runbook:` annotation) keep their path; the
  alerts point at `https://github.com/jamaomonov/csmarket/blob/main/docs/runbooks/…`.
