# Incidents

Index of incident reports for this fork. Reports describe **synthetic** rehearsals unless stated
otherwise; they do not assert any real customer, deployment or production recovery. A report on an
unmerged branch is a proposal for human review, not merged documentation.

| ID | Title | Status | Issue | PR |
|---|---|---|---|---|
| INC-2 | [Stale reschedule confirmation accepts a blocked hour](INC-2-stale-reschedule-confirmation.md) | Fix in draft PR, awaiting human review | [#2](https://github.com/raffimaurer/django-appointment/issues/2) | [#7](https://github.com/raffimaurer/django-appointment/pull/7) |

## Conventions

- File name: `INC-<issue number>-<short-descriptive-suffix>.md`.
- Related-risk probes and their captured output live under `demo/evidence/INC-<issue number>/`,
  outside normal test discovery.
- Never include confirmation tokens, secrets or personal data.
