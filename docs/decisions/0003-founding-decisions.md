# 0003. Founding decisions (retroactive)

Date: 2026-11-19
Status: accepted (recorded after v0.1 shipped; the decisions date from the start of the project)

## Context

Decisions 0001 and 0002 record two choices made during v0.1. The choices that shaped the project
from its first commit were never written down in this repository. This record states them once,
so the later records (0004 onwards) can refer to them. It records what was decided and the
reason that still holds today; it does not reconstruct the original discussion.

## Decisions

| Topic | Decision | Reason |
|---|---|---|
| Shape | One service made of modules (`erp_sim`, `brain`, `verifier`, `channels`, `shared`, `apps`), not separate services | One person builds and runs it; module boundaries give the isolation that matters and `lint-imports` enforces them |
| Languages | Python 3.13 for the backend, TypeScript for the web page (v0.2). Customer chat, shown text and test data are Rioplatense Spanish. Code, comments, specs, records and commits are English. The README is published in English and Spanish | The domain language is Spanish; the artifacts stay readable for any reviewer |
| Evals | An in-house harness (`evals/`) with recorded runs replayed offline in CI and live runs run by hand, instead of a third-party evaluation framework | The grader reads the same database and verifier the product uses, and replay keeps CI free of network calls and API spend |
| Repository | Public, MIT license, with all data fictitious (a fiction notice in the README) | The work is meant to be read and run; no real company or customer data exists in it |
| Method | Spec-driven: each release is one short change (proposal, specs, design, tasks) built in small chained PRs of up to 400 changed lines, reviewed against the spec | Scenarios give a mechanical definition of done, and small PRs stay reviewable |
| Delivery order | v0.1 terminal channel and the verifier; v0.2 local web page and the model comparison; v0.3 deploy with the limits a public demo needs. Each release must stand on its own | A later release never blocks an earlier one |
| Demo intent | The goal is a live demo that a person can try (v0.3), after the verified-order behavior is proven locally | Trying it beats reading about it, but only a verified core is worth showing |
| Video | Dropped. No video or recording of any kind is part of any release | Decided 2026-11-19 (v0.2 planning); the live demo and the written records replace it |

## Consequences

- Later records may rely on this table instead of repeating it.
- A change to any row is a new record that supersedes this one for that row.
