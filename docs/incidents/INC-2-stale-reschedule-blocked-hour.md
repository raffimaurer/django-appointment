# INC-2: Stale reschedule confirmation accepts a blocked hour

!!! note "Synthetic rehearsal"
    All people, appointments and blocks are synthetic. This is a local demo
    rehearsal, not a production outage. No real customer or NHS affiliation is
    asserted, and no production recovery is claimed.

| | |
| --- | --- |
| Issue | [#2](https://github.com/raffimaurer/django-appointment/issues/2) |
| Pull request | [#12](https://github.com/raffimaurer/django-appointment/pull/12) (draft, unmerged, targets `demo/ready`) |
| Base | `demo/ready` @ [`757f2517de2d1728f211f8890939d8800fd39051`](https://github.com/raffimaurer/django-appointment/commit/757f2517de2d1728f211f8890939d8800fd39051) |
| Fix commit | [`75d33c3`](https://github.com/raffimaurer/django-appointment/commit/75d33c3) |
| Lint-only follow-up | [`2d77173`](https://github.com/raffimaurer/django-appointment/commit/2d77173) (blank line in the new test file) |
| Evidence commit | [`6f0e9a6`](https://github.com/raffimaurer/django-appointment/commit/6f0e9a60442cf8a2fe8565a8d2a474321d69b34f) |
| Environment | Python 3.12.16, `demo-requirements.lock`, `appointments.demo_settings`, SQLite test DB, in-memory (`locmem`) email |

## Symptom

A client submits a reschedule to 10:00–11:00 and gets a confirmation link
(valid for 5 minutes). Before they click it, the staff member adds an
`Unavailability` covering that hour. Fresh availability correctly hides 10:00.
Following the original link still moves the appointment into the blocked hour,
marks the request confirmed and notifies the admin.

## Expected behaviour (from the issue)

- Same-staff, same-date overlap: a useful 400/409 rejection.
- Every original appointment and pending-history field is preserved; no
  success notification.
- Valid rescheduling, adjacent intervals and blocks for another staff member or
  date remain allowed.

## Cause

`confirm_reschedule` (`appointment/views.py`) validated only
`reschedule_status == 'pending'` and `AppointmentRescheduleHistory.still_valid()`
before writing the new date/time to the `AppointmentRequest`. Unavailability is
checked when slots are **offered** (`get_available_slots_for_staff`), but not
at **commit**, so a block added during the hold window was ignored.

## Repair

Fix commit [`75d33c3`](https://github.com/raffimaurer/django-appointment/commit/75d33c3):

- New `has_unavailability_overlap(staff_member, date, start_time, end_time)` in
  `appointment/utils/db_helpers.py`. It uses half-open `[start, end)` semantics
  (`start_time__lt=end_time`, `end_time__gt=start_time`), scoped to the same
  staff member and date.
- `confirm_reschedule` calls it after the existing expiry/status checks and
  before any write. On overlap it renders the existing error page with HTTP 409
  and the message "Sorry, this time is no longer available. Please choose
  another time." Nothing is saved, the admin is not notified, no flash message
  is added and no thank-you session access is granted.
- The existing `get_unavailabilities_for_date_and_time` helper was not reused:
  it uses `lte`/`gte`, which would wrongly reject a block that only touches
  the slot boundary.
- The rejected pending request is left exactly as it was (the issue requires
  every pending-history field to be preserved). If the block is removed while
  the link is still valid, the same link confirms normally.

## Regression coverage

`appointment/tests/test_reschedule_confirm_blocked_time.py` (9 tests, added
before the production change):

| Test | Before fix | After fix |
| --- | --- | --- |
| `test_exact_block_rejected_and_every_field_preserved` (all concrete fields of request, history and appointment; no mail, messages or thank-you session key; 409 body) | FAIL | ok |
| `test_enclosing_block_rejected` | FAIL | ok |
| `test_block_inside_slot_rejected` | FAIL | ok |
| `test_block_overlapping_start_rejected` | FAIL | ok |
| `test_rejected_link_still_works_once_block_removed` | FAIL | ok |
| `test_block_ending_at_slot_start_allowed` (adjacent before) | ok | ok |
| `test_same_staff_block_on_other_date_allowed` | ok | ok |
| `test_expired_link_with_block_is_not_applied` (expiry still wins: 404) | ok | ok |
| `test_replay_after_confirmation_does_not_move_again` | ok | ok |

The seven acceptance tests in `appointment/tests/test_incident_reschedule.py`
are unchanged.

## Test results (local)

Commands use `DJANGO_SETTINGS_MODULE=appointments.demo_settings .venv/bin/python manage.py test ...`.
Extracts are in [`test-results.txt`](https://github.com/raffimaurer/django-appointment/blob/6f0e9a60442cf8a2fe8565a8d2a474321d69b34f/demo/evidence/INC-2/test-results.txt).

| Run | Ran | Failures | Errors | Skipped |
| --- | --- | --- | --- | --- |
| Baseline incident tests (`757f251`) | 7 | 3 | 0 | 0 |
| Baseline full suite (`757f251`) | 576 | 3 | 0 | 3 |
| New tests before fix | 9 | 5 | 0 | 0 |
| Incident + new tests after fix | 16 | 0 | 0 | 0 |
| Full suite after fix | 585 | 0 | 0 | 3 |

The three baseline failures are exactly the three intentionally failing
acceptance tests. No other baseline failure existed. Hosted `demo-verify` and
Devin Review results for the final head are recorded in the PR description and
the issue handoff, not in this file.

## Related-risk probes (timeboxed, 10 minutes)

Script: [`related_risk_probes.py`](https://github.com/raffimaurer/django-appointment/blob/6f0e9a60442cf8a2fe8565a8d2a474321d69b34f/demo/evidence/INC-2/related_risk_probes.py);
actual output: [`related_risk_probes_output.txt`](https://github.com/raffimaurer/django-appointment/blob/6f0e9a60442cf8a2fe8565a8d2a474321d69b34f/demo/evidence/INC-2/related_risk_probes_output.txt).
The probes run outside normal test discovery and only print observed behaviour.

| Probe | Observed | Status |
| --- | --- | --- |
| Confirm after a `DayOff` is added for the target date | 302, moved, admin notified | **Reproduced** (not fixed, out of scope) |
| Confirm into a slot another appointment now holds for the same staff | 302, moved, admin notified | **Reproduced** (not fixed) |
| Confirm after the staff member's working hours are removed | 302, moved, admin notified | **Reproduced** (not fixed) |
| Submit a reschedule into an hour that is already blocked | 200, pending request created, confirmation email sent | **Reproduced** at submit (the new confirm check then rejects it) |
| Reschedule page right after a rejected confirmation, `reschedule_limit=1` | 409, then reschedule page 403 | **Reproduced**: the kept pending row counts toward the 5-minute limit |
| Pending request whose `staff_member` is `NULL` (staff deleted) with a block for the original staff | 302, moved | **Reproduced**; the check has no staff to scope to |

**Suspected only (not tested):** a block saved between the new check and the
write would not be seen. The check and the write are not in one transaction
with row locking. SQLite serialises writes, so this concurrency risk is
**unverified** and no concurrency claim is made.

## Remaining risks

- The commit step still does not re-validate days off, working hours or other
  bookings (reproduced above).
- After a rejection the client may be unable to start a new reschedule for up
  to 5 minutes when the reschedule limit is 1 (reproduced). Changing that needs
  a decision because the issue requires the pending row to stay unchanged.
- Check-then-write race (suspected, unverified on SQLite).
- The 409 page reuses the `404_not_found.html` template, so its `<title>`
  reads "Page not found | 404" while the heading shows the conflict message.

## Proposed follow-ups (not filed)

1. Re-validate the whole target slot (days off, working hours, other bookings)
   at confirmation with one shared availability check.
2. Validate unavailability at reschedule **submit** so no link is emailed for an
   already-blocked hour.
3. Decide how a rejected pending request should count toward
   `reschedule_limit`, and evaluate locking on the production database engine.

## Review outcome

See [PR #12](https://github.com/raffimaurer/django-appointment/pull/12) for the final-head Devin Review findings and how each
was handled.
