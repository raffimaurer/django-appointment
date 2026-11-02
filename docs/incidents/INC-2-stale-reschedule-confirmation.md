# INC-2: Stale reschedule confirmation accepts a blocked hour

!!! note "Synthetic rehearsal"
    All data is synthetic. No real customer, NHS relationship, deployment or production recovery is
    asserted. This report lives on an unmerged draft branch and is a proposal for human review.

## Links

- Issue: [#2](https://github.com/raffimaurer/django-appointment/issues/2)
- Draft PR: [#7](https://github.com/raffimaurer/django-appointment/pull/7) (base `demo/ready`)
- Base commit: [`757f2517`](https://github.com/raffimaurer/django-appointment/commit/757f2517de2d1728f211f8890939d8800fd39051)
- Fix commit (tested code): [`06ed831f`](https://github.com/raffimaurer/django-appointment/commit/06ed831fd0001f105ea5bdb3b55ce49348256ad4)
- Evidence commit (CI-verified head): [`873fbd80`](https://github.com/raffimaurer/django-appointment/commit/873fbd800c9fceba8b4679266c022b8e4858f5e7)
- Hosted CI: [demo-verify run 41538072398](https://github.com/raffimaurer/django-appointment/actions/runs/41538072398),
  [verify job log](https://github.com/raffimaurer/django-appointment/actions/runs/41538072398/job/125594912651)
- Related-risk evidence: [`demo/evidence/INC-2/`](https://github.com/raffimaurer/django-appointment/tree/devin/1793658653-inc2-stale-reschedule-confirmation/demo/evidence/INC-2)
- Procedure followed: `.agents/skills/scheduling-incident-investigation/SKILL.md` on `demo/ready` @ `757f2517`

## Symptom and impact

A still-valid (under five minutes old) reschedule confirmation link moved an appointment into an hour
the practitioner had blocked with an `Unavailability` **after** the reschedule was requested. A fresh
availability lookup correctly hid that hour, and the admin was notified of a "successful" reschedule.
Illustrative impact: a conflicting booking that needs manual reconciliation.

## Reproduction

Environment (Skill §1): Python 3.12.16, `demo-requirements.lock`,
`DJANGO_SETTINGS_MODULE=appointments.demo_settings`, SQLite, in-memory mail. `manage.py check`,
`makemigrations appointment` and `migrate` were run first; generated migrations are not committed.

```bash
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py test appointment.tests.test_incident_reschedule -v 2
.venv/bin/python manage.py test appointment
```

Reproduced on the unmodified base before editing (Skill §2): the three failing acceptance tests showed
the appointment moved to the blocked 10:00–11:00 slot (`INCIDENT: confirmation moved appointment into
newly blocked time`), matching the reported symptom.

## Root cause

Tracing offer → hold → commit (Skill §3):

- **Offer**: `get_available_slots_for_staff` excludes `Unavailability` rows, so listings are correct.
- **Hold**: `reschedule_appointment_submit` creates a pending `AppointmentRescheduleHistory` and emails a link.
- **Commit**: `confirm_reschedule` checked only `reschedule_status == 'pending'` and `still_valid()`
  (the five-minute window). It never re-read current availability, so anything that changed between
  hold and commit was ignored before it saved `AppointmentRequest`, flipped the history row to
  `confirmed` and called `notify_admin_about_reschedule`.

## Fix

`confirm_reschedule` now calls a new helper before any write or notification and returns **409** with
a user-safe message if the requested interval overlaps a current block:

```python
has_overlapping_unavailability(date, start_time, end_time, staff_member)
# Unavailability.objects.filter(staff_member=..., date=..., start_time__lt=end_time, end_time__gt=start_time).exists()
```

- Half-open `[start, end)` semantics, same staff and same date only (Skill §4). The existing
  `get_unavailabilities_for_date_and_time` uses inclusive `lte`/`gte` and would wrongly reject an
  adjacent block, so it was neither reused nor changed.
- Rejection is side-effect free (Skill §5): no `AppointmentRequest` or history-row change, no
  notification, and the pending link remains usable if the block is later removed.

### Prevention principle

**Revalidate mutable availability at confirmation, before changing data or sending notifications.**
An offer or hold is a snapshot; staff blocks, days off, working hours and other bookings can change
before the commit. The commit step must check current state and fail closed without side effects.

## Test results

Counts are from Django's `Ran N tests` / `OK|FAILED` lines. "Passed" is derived as run − failures −
errors − skipped.

| Run | Where | Commit | Run | Passed | Failed | Skipped |
|---|---|---|---|---|---|---|
| Incident acceptance, before | local | `757f2517` | 7 | 4 | 3 | 0 |
| Full suite, before | local | `757f2517` | 576 | 570 | 3 | 3 |
| Incident acceptance, after | local | `06ed831f` | 7 | 7 | 0 | 0 |
| Acceptance + regression, after | local | `06ed831f` | 13 | 13 | 0 | 0 |
| Full suite, after | local | `06ed831f` | 582 | 579 | 0 | 3 |
| Full suite, hosted demo-verify | GitHub Actions | `873fbd80` | 582 | 579 | 0 | 3 |

- The three skips are `Django-Q is not available` (`DjangoQUnavailableTest`,
  `ScheduleEmailReminderTest`, `UpdateAppointmentReminderTest`), identical before and after.
- Hosted evidence source: the verify **job log** (`Ran 582 tests in 5.653s`, `OK (skipped=3)`, all
  13 incident tests `ok`), run on Python 3.12.15 by `actions/setup-python`. The `test-output`
  artifact exists (ID 13185072785) but downloading it was blocked by this session's network policy
  (blob storage host not allowlisted). That is an evidence-access limitation, not a test failure.
- `873fbd80` differs from `06ed831f` only by adding `demo/evidence/INC-2/` (not discovered by the suite).
- Local runs are not hosted CI.

## Regression tests

The seven acceptance tests in `appointment/tests/test_incident_reschedule.py` are unchanged. New tests
in `appointment/tests/test_reschedule_confirmation_revalidation.py`:

| Test | Prevents |
|---|---|
| `test_rejection_preserves_pending_history_and_sends_no_mail` | A rejection that swaps/flips any pending-history field or sends mail |
| `test_link_confirms_after_block_is_removed` | A rejection that consumes the link or a check that keys on stale state |
| `test_containing_and_contained_blocks_rejected` | Missing containing, contained or leading-edge overlaps |
| `test_block_ending_at_start_allowed` | Closed-interval over-rejection at the start boundary |
| `test_same_staff_block_on_other_date_allowed` | Ignoring the date scope |
| `test_helper_uses_half_open_intervals` | Regressing the helper's interval or staff scoping |

Together with the acceptance tests (adjacent-after block and other-staff block allowed, full and
partial overlap rejected, real submit → block → confirm rejected), any reintroduction of an
unchecked commit or a closed-interval check fails CI.

## Review findings

Devin Review on `873fbd80` reported **1 finding**:

| Finding | Severity | Handling |
|---|---|---|
| Concurrent block escapes reschedule revalidation (check-then-write without serialisation, `appointment/views.py`) | bug | **Escalated to human** (`needs_human`), [thread reply](https://github.com/raffimaurer/django-appointment/pull/7#discussion_r4448598381). Not reproduced; SQLite serialises writes, so no race claim is made. A real fix needs a lock or constraint honoured by every `Unavailability` writer, beyond this incident's scope. Listed as follow-up 2. |

- **Automatic corrections (Auto-Fix):** Auto-Fix was enabled for the review, but **no automatic code
  correction was applied**; the single finding was triaged and escalated, not auto-fixed.
- **Human-directed corrections:** none.
- **Advisory notes (own inspection, no change):** the 409 page reuses `error_pages/404_not_found.html`,
  whose page title reads "Page not found | 404" (concern I4).

Results for later PR heads (the documentation commits) are recorded in the PR description and the
final issue handoff comment, not by further report commits.

## Remaining risks

Bounded 10-minute audit of sibling commit paths (Skill §9). Probes: `demo/evidence/INC-2/probe_related_risks.py`,
output `probe-output.txt`, run on `06ed831f`. None are fixed in this PR.

**Reproduced defects** (probe demonstrates the behaviour):

- **R1** A `DayOff` added after the request is not rechecked; confirmation returns 302, moves the
  appointment and notifies the admin.
- **R2** An overlapping appointment booked for the same staff/slot after the request is not rechecked;
  confirmation moves the appointment into a double booking.
- **R3** `reschedule_appointment_submit` accepts a slot that is already blocked (pending row created,
  confirmation email sent). By code reading, the new confirmation check would then reject it, but the
  client still receives a misleading email.

**Inspection concerns** (code reading only, not reproduced):

- **I1** Check-then-write race between `has_overlapping_unavailability` and the save (Review finding).
  Unverified; would need PostgreSQL and concurrent requests.
- **I2** Working-hours edits after the request are not rechecked at confirmation.
- **I3** Confirmation is a state-changing `GET`, so link prefetchers or scanners could confirm.
- **I4** The 409 response renders a page titled "404".

## Prioritised follow-ups (proposals, not created)

1. One `slot_still_bookable(...)` check (unavailability, days off, working hours, other appointments)
   used by both reschedule submit and confirmation (R1, R2, R3, I2).
2. Serialise availability writes and confirmation (e.g. `transaction.atomic` + `select_for_update` on
   the `StaffMember`), verified on PostgreSQL (I1).
3. Make confirmation a `POST` from an interstitial page with a dedicated 409 template (I3, I4).

## Proposed Skill updates (for human review; Skill unchanged)

- §4: before reusing an existing overlap helper, check its interval semantics (this repo's
  `get_unavailabilities_for_date_and_time` is inclusive).
- §5: require the rejection test to assert every pending-history field and an empty `mail.outbox`.
- §9: store bounded probes under `demo/evidence/INC-<n>/` with a non-`test*` name and captured output.
- §10: when artifact download is blocked, use the hosted job log as evidence and record run, commit,
  run/passed/failed/skipped counts and the evidence source.

## Limitations

- Local `flake8` and `mkdocs` were run from a separate tools virtualenv, not from `demo-requirements.lock`.
- Hosted artifact not downloaded (network policy); job log used instead.
- No concurrency testing; no deployment; no post-release verification.

## Human decision checklist

- [ ] Inspect the latest PR head's demo-verify result and Devin Review status.
- [ ] Decide on the escalated race finding (I1) and remaining risks R1–R3, I2–I4.
- [ ] Approve or request changes on [PR #7](https://github.com/raffimaurer/django-appointment/pull/7).
- [ ] If approved, follow the team's release and post-release verification process (not done here).
