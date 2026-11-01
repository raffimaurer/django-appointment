# INC-001 — Stale reschedule confirmation moves appointment into newly blocked time

> Simulated incident, synthetic data, no real customer/NHS affiliation. Base: `demo/incident` @
> `fe26aca0ade5789bb2b5c4a0c038e46854a7b452` (verified with `git rev-parse HEAD` before any change).
> Environment: CPython 3.12.16 (uv), `demo-requirements.lock` (Django 6.1.2), `DJANGO_SETTINGS_MODULE=appointments.demo_settings`
> (SQLite, locmem email, `USE_DJANGO_Q_FOR_EMAILS = False`, no workers).

## 1. Root cause

Request/data flow:

1. `reschedule_appointment_submit` (`appointment/views.py:596`) validates only `AppointmentRequestForm` and creates an
   `AppointmentRescheduleHistory` row (`views.py:615`, status `pending`) holding the *requested* date/time/staff, then
   emails a link to `confirm_reschedule/<id_request>`.
2. The practitioner adds an `Unavailability`. Slot listing (`get_available_slots_for_staff`, `appointment/services.py:555`)
   reads unavailabilities on every call, so the slot disappears from fresh lookups.
3. `confirm_reschedule` (`views.py:638`) checked only `reschedule_status == 'pending'` and `still_valid()` (created < 300 s
   ago). It then copied the stored slot onto the `AppointmentRequest` (`ar.save`), flipped the history row to `confirmed`,
   added a success message and called `notify_admin_about_reschedule`.

Root cause: availability was enforced only in the slot listing, i.e. at *offer* time. The confirmation step trusted
a snapshot taken at submit time and never re-checked current staff unavailability before mutating. Any block created
between submit and confirm was therefore ignored.

## 2. Repair

- `appointment/utils/db_helpers.py`: new `staff_unavailability_overlaps(staff_member, date, start_time, end_time)`,
  a single `EXISTS` query with half-open semantics `block.start < end AND block.end > start`, scoped to the same
  staff member and date. A block ending exactly at the appointment start or starting exactly at its end is adjacent
  and allowed.
- `appointment/views.py` `confirm_reschedule`: after the existing pending/expiry guard and **before any write**, if
  the requested slot overlaps a block, return **HTTP 409** with the message "Sorry, the requested time is no longer
  available. Your appointment has not been changed; please choose another time." (rendered with the existing
  error template). Nothing is saved, so the `AppointmentRequest` and the pending history row (all fields, status,
  `id_request`) stay unchanged. No success message, no admin notification, no email.
- Valid (unblocked) confirmation is unchanged.

Design notes:
- The pending row stays `pending` after a rejection, so pending-history integrity holds. If the block is removed
  while the 5-minute link is still valid, the same link can still be confirmed. This is covered by a test and
  deliberately chosen over consuming the request.
- The 409 page reuses `error_pages/404_not_found.html` to keep the diff minimal. The visible message is correct, but
  the HTML `<title>` still says "404". A dedicated template is a cosmetic follow-up.
- Scope is limited to `Unavailability` as specified. Other stale-state gaps found in the audit (§5) are **not** fixed here.

## 3. Before / after evidence

All commands run from the repo root with `DJANGO_SETTINGS_MODULE=appointments.demo_settings`.

| Run | Command | Result |
|---|---|---|
| Before (base source) | `.venv/bin/python manage.py test appointment.tests.test_incident_reschedule -v 2` | Ran 7, **FAILED (failures=3)** |
| Before (base source) | `.venv/bin/python manage.py test appointment` | Ran 576, **FAILED (failures=3, skipped=3)** |
| New tests vs base `views.py` (helper present, view unchanged; temporary worktree) | `... manage.py test appointment.tests.test_reschedule_unavailability_guard -v 2` | Ran 10, **FAILED (failures=4)**: containment, inside-slot, unmocked-email, replay-after-rejection (each `302 != 409`) |
| After | `.venv/bin/python manage.py test appointment.tests.test_incident_reschedule -v 2` | Ran 7, **OK** |
| After | `.venv/bin/python manage.py test appointment.tests.test_reschedule_unavailability_guard -v 2` | Ran 11, **OK** (10 original + 1 log-redaction test, §8) |
| After | `.venv/bin/python manage.py test appointment.tests.test_views.ConfirmRescheduleViewTests appointment.tests.test_views.RescheduleAppointmentSubmitViewTests` | Ran 9, **OK** |
| After | `.venv/bin/python manage.py test appointment` | Ran **587**, **OK (skipped=3)**, 0 failures, 0 errors (after the §8 review correction; 586 before it) |
| Lint | `flake8 --max-line-length 120` on changed lines / new test file | no findings on new code (pre-existing findings elsewhere in `views.py`/`db_helpers.py` untouched) |

Failing assertion before the fix (excerpt):

```
FAIL: test_confirmation_rejects_new_block_without_mutation
AssertionError: Tuples differ: (datetime.date(2026, 11, 8), datetime.time(10, 0), datetime.time(11, 0), 1)
                            != (datetime.date(2026, 11, 7), datetime.time(9, 0), datetime.time(10, 0), 1)
 : INCIDENT: confirmation moved appointment into newly blocked time
FAIL: test_partial_overlap_rejected          AssertionError: datetime.date(2026, 11, 8) != datetime.date(2026, 11, 7)
FAIL: test_real_submit_then_block_then_confirm AssertionError: datetime.date(2026, 11, 8) != datetime.date(2026, 11, 7)
Ran 7 tests ... FAILED (failures=3)
```

The 587 total is the 576 baseline plus 11 new tests. The 7 incident acceptance tests are unmodified.

New coverage (`appointment/tests/test_reschedule_unavailability_guard.py`):
- Helper: half-open table (adjacent before/after allowed; identical, start-overlap, end-overlap, inside, containing
  rejected); staff and date scoping.
- View: containing block → 409, every `AppointmentRequest` and pending field unchanged, single history row, no notify,
  empty outbox, no success message; block inside slot → 409; unmocked notify → empty outbox; adjacent-before block
  allowed; same time on a different date allowed; genuinely expired link (`created_at` backdated 6 min, no mock) → 404
  with no mutation; replay after success → 404, notified once; replay after rejection stays 409, then succeeds once
  the block is removed within the window.

## 4. What these tests do **not** prove

- **No concurrency safety is claimed.** The tests are sequential on SQLite. The check and the writes are not in a
  transaction, and there is no `select_for_update`, no DB-level exclusion constraint and no `ATOMIC_REQUESTS`
  (`appointments/settings.py:87`). A block inserted between the `EXISTS` check and `ar.save()` (a window of milliseconds),
  or two concurrent clicks on the same link, can still slip through or cause duplicate notifications. Closing this
  needs a transaction plus row locking on a backend that supports it (PostgreSQL), or an exclusion constraint, and has
  to be tested on that backend.
- Confirmation still does not re-check other appointments, days off or working hours (see §5).

## 5. Adjacent stale-state risk register (audit time-boxed to 15 min)

Repro scripts are kept out of the PR. They live in a scratch `TestCase` (`test_zz_audit_scratch.py`, deleted after
running) where each test passes when the defect **is** reproduced: **Ran 6, OK**, i.e. all 6 reproduced on the patched branch.
Line numbers refer to this branch.

### Reproduced defects

| ID | Location | Impact | Evidence | Next action |
|---|---|---|---|---|
| A1 | `views.py:596-627` `reschedule_appointment_submit` | Accepts a slot that is **already** blocked when submitted and emails a confirmation link (the confirm step now rejects it, but the client receives a misleading email). | POST submit after creating a 10–11 block → 200, history row created, `send_reschedule_confirmation_email` called once. | Run the same availability check at submit time and return a form error. Separate PR. |
| A2 | `views.py:638-686` `confirm_reschedule` | **Double booking**: confirmation ignores a different client's appointment booked into the slot after submit. | Pending 10–11 → other appointment for staff 1 at 10–11 → confirm 302 → 2 requests for staff 1 at 10:00. | Extend the confirm-time check to overlapping appointments (excluding self). Needs a product decision and a transaction/locking design. |
| A3 | `views.py:638-686` | Confirmation ignores a `DayOff` added after submit (slot listing returns `[]`). | `get_available_slots_for_staff(...) == []`, confirm 302, appointment moved. | Same as A2: include day off / working hours in the confirm-time revalidation. |
| A4 | `views.py:250-269` `appointment_request_submit` (and `appointment_client_information` → `create_and_save_appointment`, `db_helpers.py:117-129`) | **New booking** accepts a blocked slot. Availability is enforced only in the UI slot list, so a crafted or stale POST creates an `AppointmentRequest`. | POST 10–11 with a block present → 302, `AppointmentRequest` created. | Validate availability server-side before `form.save()` and again before `Appointment` creation. |
| A5 | `db_helpers.py:431-454` `exclude_pending_reschedules` | Filters pending holds by `appointment_request__staff_member` (the **old** staff), not the history's target `staff_member`. When staff change is allowed, a pending move to staff 2 does not hide staff 2's slot. | Pending to staff 2 at 10:00 → staff 2 slot list still contains 10:00. | Filter on `staff_member=staff_member`. Also consider slot+duration overlap rather than slot-start-in-range. |
| A6 | `views.py:672-686` (cancellation interplay) | If the appointment is **deleted/cancelled** after submit, confirm saves the `AppointmentRequest` and marks the history `confirmed`, then raises `Appointment.DoesNotExist` at `views.py:683` (HTTP 500). Writes are not atomic, so partial state persists. | After `appointment.delete()`, confirm raises `DoesNotExist`; request moved 2026‑11‑07 09:00 → 2026‑11‑08 10:00; history `confirmed`. | Resolve the `Appointment` before writing (404/409 if missing) and wrap the writes in `transaction.atomic()`. |

### Inspection concerns (not reproduced)

| ID | Location | Concern | Next action |
|---|---|---|---|
| C1 | `views.py:641` / `679` | Replay is guarded by a read-then-write status check with no lock. Concurrent clicks could both pass and double-notify. Not reproducible with sequential SQLite tests. | Conditional update (`filter(pk, reschedule_status='pending').update(...)`, check rowcount) inside a transaction. Test on PostgreSQL. |
| C2 | `db_helpers.py:419-425` vs new helper | Slot listing applies the staff `gap_time` around unavailabilities. The confirm guard uses strict half-open overlap (as specified), so with `gap_time > 0` the guard allows an adjacent slot that the listing would hide. | Product decision: should gap time apply to blocks at confirm time? |
| C3 | `admin` / `services.py` unavailability creation | Creating a block does not warn about existing or pending appointments it overlaps. | Optional warning when saving a block. |

## 6. Reusable scheduling investigation checklist

1. Pin the base SHA, interpreter, lockfile and settings, and record them.
2. Run the acceptance tests **before** editing source and save the full output (red).
3. Map the flow *offer → hold → commit*: which step reads live state, which step trusts a snapshot?
4. For every commit step (create, confirm, move, cancel), list each constraint the offer step enforced (blocks, days
   off, working hours, other bookings, pending holds, gap/buffer) and check whether commit re-checks it.
5. Define interval semantics explicitly (half-open `[start, end)`) and test both adjacency edges, partial overlap,
   containment, inside, and different staff/date.
6. Check **ordering**: validation must run before the first write and before every side effect (messages, email,
   notifications, reminders).
7. On rejection, assert that *every* field of every touched row is unchanged, not just one field.
8. Cover expiry with real time manipulation (backdate `created_at`), and cover replay after success and after rejection.
9. Prove each new test is meaningful by running it against the unfixed source.
10. Never log bearer tokens (`id_request` confirmation links, reset tokens). Log row PKs instead and prove it with an `assertLogs` test.
11. Do not claim race safety from sequential SQLite tests. Write down the transaction/locking assumptions and leave
    them as an explicit risk.
12. Time-box the adjacent audit. Separate *reproduced* from *suspected*, and keep unrelated fixes out of the incident PR.

## 7. Draft Devin Skill (not yet saved or verified across sessions)

```markdown
---
name: scheduling-stale-state-investigation
description: Investigate and repair booking/reschedule bugs where a commit step trusts state captured at offer time.
---
1. Verify base SHA; set up the pinned interpreter/lockfile/settings; generate git-ignored migrations locally and never commit them.
2. Reproduce first: run the acceptance tests on unmodified source; save the output as red evidence.
3. Trace offer → hold → commit. List the constraints the offer step enforces and check whether commit re-checks them.
4. Fix at the commit step with a small helper that uses half-open overlap (`a.start < b.end and a.end > b.start`), scoped to staff and date, called before any write or side effect. Return 409 with a user-facing message.
5. Tests: adjacency both sides, partial, inside, containing, other staff, other date, real expiry, replay after success/rejection, and full-row immutability with no notifications or outbox mail. Run the new tests against the old source to prove they fail.
6. Run the targeted tests and the full suite, and report exact counts and skips.
7. Audit sibling flows (new booking, submit, confirm, cancel, slot listing) with throwaway repro tests. Report reproduced vs inspected, with file:line, impact and next action. Do not broaden the fix.
8. Never claim concurrency safety from SQLite tests; record transaction/locking gaps.
9. Never put confirmation/reset tokens (e.g. `id_request`) in log lines or error messages; log the row PK and add an `assertLogs` test.
```

## 8. Devin Review finding and correction (CWE-532)

- **Finding:** Devin Review on the draft PR flagged "Reschedule confirmation token leaked to logs" (CWE-532) at
  `appointment/views.py:650`. The original fix commit added
  `logger.warning(f"Reschedule {id_request} rejected: ...")`. `id_request` is the bearer token in the
  `confirm-reschedule/<id_request>/` link, so anyone who can read the logs could replay a still-valid link. The
  requester confirmed this independently. I introduced this defect in the first fix commit.
- **Correction:** the warning now logs the non-secret row primary key:
  `logger.warning(f"Reschedule {reschedule_history.pk} rejected: ...")`. Behaviour, status code and scheduling logic
  are unchanged.
- **Test:** `test_rejection_log_omits_confirmation_token` captures `appointment.views` WARNING output for a rejected
  confirmation. It asserts exactly one rejection line, that the line contains `Reschedule <pk> rejected`, and that
  the token string appears in no captured line.
- **Red (before the correction):**
  `manage.py test appointment.tests.test_reschedule_unavailability_guard.ConfirmRescheduleUnavailabilityGuardTests.test_rejection_log_omits_confirmation_token`
  → Ran 1, FAILED (failures=1):
  `AssertionError: 'Reschedule 1 rejected' not found in 'WARNING:appointment.views:Reschedule <synthetic 48-char token> rejected: ...'`
  (the token from the synthetic test DB is shortened here).
- **Green (after the correction):** guard tests Ran 11 OK; incident tests Ran 7 OK (file unmodified); full suite
  Ran 587, OK (skipped=3). Rejection warnings in the full-suite log now read `Reschedule 1 rejected` / `Reschedule 2
  rejected`.
- **Not changed (out of scope, pre-existing upstream):** `views.py:558` in `prepare_reschedule_appointment` logs the
  appointment request's `id_request` at ERROR level. That value is also part of client-facing URLs, so it is the same
  class of exposure. Recommended as a separate follow-up.
