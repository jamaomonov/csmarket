# Incident template

`ApiHighErrorRate` links here. When a page lands, stop the impact first and write this up
after.

## First ten minutes

1. **Was there a deploy in the last hour?** If so and the errors started with it, roll back to
   the previous `sha-` tag ([`deploy.md`](deploy.md#rollback)) and investigate afterwards.
2. **Which route?** Grafana → "API · Overview" dashboard, or Prometheus:
   `sum by (handler) (rate(http_requests_total{job="api",status="5xx"}[5m]))`.
3. **What is the error?** Sentry (csmarket project) for the stack trace; Loki
   (`{container="csmarket-prod-api-1"}`) for the log lines around it.
4. **Is a dependency down?** `curl -fsS https://api.csmarket.uz/readyz` names a failing
   Postgres or Redis check. Pool exhaustion and saturation: [`traffic-surge.md`](traffic-surge.md).
5. Tell the owner in one line what is broken and what you are doing about it. Anything that
   could drop or delete data waits for the owner's answer.

Then copy the template below into a new file and fill it in.

## Template

```markdown
# Incident NNNN — <short title>

- **Status**: Open | Mitigated | Resolved | Post-mortem complete
- **Severity**: SEV1 (full outage) | SEV2 (degraded) | SEV3 (partial)
- **Start**: YYYY-MM-DD HH:MM UTC
- **End**: YYYY-MM-DD HH:MM UTC
- **Incident commander**: @handle
- **Tags**: payments | waxpeer | steam | infra | data | other

## Summary

One-paragraph plain-English summary, suitable for a status page.

## Impact

Who was affected, how many, what they saw. Orders by number and amounts are fine here; no
Steam IDs, emails, IPs or trade links.

## Timeline (UTC)

- HH:MM — first signal (alert / customer report / etc.)
- HH:MM — investigation started
- HH:MM — root cause hypothesised
- HH:MM — mitigation applied
- HH:MM — fully resolved

## Root cause

What caused this. Be specific.

## Mitigation

Exact steps taken to stop the impact.

## Resolution

The change that prevents recurrence (PR link, ADR if applicable).

## Action items

- [ ] Tracked issue link + owner — short description

## What went well

- …

## What went poorly

- …

## Where we got lucky

- …
```
