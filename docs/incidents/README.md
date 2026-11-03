# Incident index

Synthetic incident rehearsals for this fork. Each entry links its report, issue and draft PR. Nothing listed here has been
deployed, and no production recovery is claimed.

| Incident | Status | Report | Issue | PR |
|---|---|---|---|---|
| INC-2: stale reschedule confirmation accepts a blocked hour | Fix in **draft, unmerged** PR; awaiting human review | [Report](INC-2-stale-reschedule-confirmation.md) | [#2](https://github.com/raffimaurer/django-appointment/issues/2) | [#6](https://github.com/raffimaurer/django-appointment/pull/6) |
| INC-8: confirmation for a deleted appointment changes records, then fails | Fix in **draft, unmerged** PR; awaiting human review | [Report](INC-8-deleted-appointment-reschedule-confirmation.md) | [#8](https://github.com/raffimaurer/django-appointment/issues/8) | [#11](https://github.com/raffimaurer/django-appointment/pull/11) |

## INC-2 at a glance

- **Outcome:** `confirm_reschedule` now re-checks same-staff, same-date `Unavailability` using half-open intervals before it writes
  anything or sends notifications. A conflict returns 409 and leaves the appointment and the pending request unchanged.
- **Tests:** the 7 acceptance tests went from 3 failed to all passed. The full suite went from 576 run (570 passed, 3 failed,
  3 skipped) to 583 run (580 passed, 3 skipped). The 3 skips are Django-Q tests.
- **Prevention principle:** revalidate mutable availability at confirmation, before changing data or sending notifications.

### Remaining risks

- **Reproduced, not fixed:** confirmation still accepts a day off, an overlapping appointment or working hours added after the request.
  See [probe evidence](https://github.com/raffimaurer/django-appointment/blob/devin/1793656832-inc-2-stale-reschedule-confirmation/demo/evidence/INC-2/README.md).
- **Inspection only (not reproduced):** no server-side check at reschedule submit; confirmation isn't atomic; staff gap time is not re-checked;
  the 409 page reuses the 404-titled template.

### Human release and verification checklist

Nothing here is done automatically. A human works through each step.

1. Review the [PR #6](https://github.com/raffimaurer/django-appointment/pull/6) diff (`appointment/views.py`, `appointment/utils/db_helpers.py`, new tests).
2. Confirm hosted `demo-verify` passed on the PR's current head (583 run, 580 passed, 3 skipped) and Devin Review has no blocking findings.
3. Optionally re-run locally: `manage.py test appointment.tests.test_incident_reschedule` (7 passed) and `manage.py test appointment`.
4. Re-run the [sibling probe](https://github.com/raffimaurer/django-appointment/blob/devin/1793656832-inc-2-stale-reschedule-confirmation/demo/evidence/INC-2/README.md) and decide whether follow-up 1 blocks release.
5. Decide on the 409 template title (follow-up 3) and whether incident pages belong on the published docs site.
6. Mark ready for review and merge only by human decision. Publishing or deploying is out of scope for the automation.

## INC-8 at a glance

- **Outcome:** `confirm_reschedule` now finds (and locks) the `Appointment` before writing. If it was deleted, the link
  returns 404 with a clear message, and the request, the pending history, notifications and session state are untouched.
  The two writes are atomic. INC-2's blocked-time rejection is unchanged.
- **Tests:** 7 new tests (2 errors + 1 failure before the fix). Full suite: 583 run (580 passed, 3 skipped) on base;
  590 run (587 passed, 3 skipped) with the fix.
- **Remaining risks:** deleted client user and deleted staff member during a pending reschedule, and submit after deletion,
  are reproduced but not fixed ([probe evidence](https://github.com/raffimaurer/django-appointment/blob/devin/1793746268-inc-8-orphaned-reschedule-confirmation/demo/evidence/INC-8/README.md)).
  Concurrency is unverified on SQLite.
- **Note:** draft [#9](https://github.com/raffimaurer/django-appointment/pull/9) is an earlier attempt at the same issue; keep only one.
