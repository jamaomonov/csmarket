# 0001. Record architecture decisions

- **Status**: Accepted
- **Date**: 2026-10-01
- **Deciders**: @jamaomonov
- **Tags**: process

## Context

csmarket is a port of a proven codebase (YuPay) into a new product, so most of its choices
arrive already made — and a future contributor, human or AI, cannot tell from the code alone
which of them were re-decided for csmarket, which were kept on purpose, and which came along
by accident. The project will also accumulate its own non-obvious choices (Waxpeer as the only
supply, the `orders` table as the queue, its own edge proxy). Without a written record each
of them gets re-litigated or silently undone.

## Decision

We record every non-trivial architectural decision as an **Architecture Decision Record
(ADR)** following the [MADR](https://adr.github.io/madr/) template, stored in
`docs/decisions/NNNN-<title>.md`. The template lives at `docs/decisions/0000-template.md`.

Numbering is strictly sequential and starts again at 0001 in this repo — YuPay's ADRs are
cited as "YuPay ADR-NNNN", never renumbered into ours. Status moves through
`Proposed → Accepted → Deprecated → Superseded by NNNN`. ADRs are **never deleted** — they
are superseded.

## Consequences

- A new dependency, framework, infra component or cross-cutting pattern comes with an ADR in
  the same change (`AGENTS.md` § 5, § 14).
- Decisions approved in the design spec (`docs/superpowers/specs/2026-10-01-csmarket-design.md`)
  do not need an ADR each; an ADR is written when a decision needs its options and
  consequences on record, or departs from the spec.
- Agents and humans write an ADR when in doubt.

## References

- [MADR template](https://adr.github.io/madr/)
- Michael Nygard, ["Documenting Architecture Decisions"](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
