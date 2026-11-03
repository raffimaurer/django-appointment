# INC-2: stale reschedule confirmation accepts a blocked hour

!!! note "Synthetic rehearsal"
    All data is synthetic. No real customer, patient or NHS relationship is implied, and this was not a
    production outage. The defect is real upstream behaviour at the demo base, not an injected regression.

| | |
| --- | --- |
| Issue | [#2](https://github.com/raffimaurer/django-appointment/issues/2) |
| Pull request | [#10 (draft, unmerged)](https://github.com/raffimaurer/django-appointment/pull/10) |
| Base | `demo/ready` @ [`757f2517`](https://github.com/raffimaurer/django-appointment/commit/757f2517de2d1728f211f8890939d8800fd39051) |
| Fix commit | [`09e5310`](https://github.com/raffimaurer/django-appointment/commit/09e531009bf86c016c31cfb1cfba7cf384e0f72d) |
| Environment | Python 3.12.16, `demo-requirements.lock` (installed packages checked against it), `appointments.demo_settings`, SQLite, locmem email |

## Symptom

A client submits a reschedule to 10:00–11:00 and receives a confirmation link that is valid for 5 minutes. Before
the client clicks it, the practitioner adds an `Unavailability` covering that hour. A fresh availability lookup
correctly hides the hour, but following the original link still moves the appointment into the blocked time
(HTTP 302), notifies the admin and staff, and grants the thank-you page.

## Cause

[`confirm_reschedule`](https://github.com/raffimaurer/django-appointment/blob/757f2517de2d1728f211f8890939d8800fd39051/appointment/views.py#L638-L677)
validated only that the `AppointmentRescheduleHistory` row was `pending` and inside the 300-second
`still_valid()` window. After that it wrote the new date and time straight to the `AppointmentRequest`.
Staff availability was checked only when slots were offered and never when the move was committed, so blocks
created between offer and commit were ignored.

The existing helper `get_unavailabilities_for_date_and_time` was not suitable for the commit check. It uses
inclusive bounds (`start_time__lte`, `end_time__gte`), so it would wrongly reject an adjacent block. Slot
listing also uses that helper, so I left it unchanged.

## Repair

Commit [`09e5310`](https://github.com/raffimaurer/django-appointment/commit/09e531009bf86c016c31cfb1cfba7cf384e0f72d):

- New [`has_overlapping_unavailability(staff_member, date, start_time, end_time)`](https://github.com/raffimaurer/django-appointment/blob/09e531009bf86c016c31cfb1cfba7cf384e0f72d/appointment/utils/db_helpers.py#L604-L609)
  checks for a half-open `[start, end)` overlap for the same staff member on the same date.
- [`confirm_reschedule`](https://github.com/raffimaurer/django-appointment/blob/09e531009bf86c016c31cfb1cfba7cf384e0f72d/appointment/views.py#L648-L654) calls it after the existing
  validity check and before any write. On a conflict it renders the existing error page with HTTP **409** and the
  message "Sorry, this time slot is no longer available. Please choose another time." Nothing is saved,
  `notify_admin_about_reschedule` is not called, no success message is added, and `allow_thank_you_page`
  is not called. The pending row stays `pending` with all of its fields unchanged.

## Evidence

Local runs: [`demo/evidence/INC-2/test-runs.txt`](https://github.com/raffimaurer/django-appointment/blob/devin/1793746272-inc-2-confirm-reschedule-blocked-hour/demo/evidence/INC-2/test-runs.txt).

| Run | Result |
| --- | --- |
| Baseline incident tests (`demo/ready`) | Ran 7, failures=3 (the three expected acceptance failures) |
| Baseline full suite (`demo/ready`) | Ran 576, failures=3, skipped=3 (same three) |
| New regression tests against unmodified production code | Ran 11, failures=5 (all `302 != 409`) |
| After fix: incident + regression tests | Ran 18, OK |
| After fix: full suite | Ran 587, OK (skipped=3); 576 existing + 11 new |
| Hosted `demo-verify` at `09e5310` | [run 41734459958](https://github.com/raffimaurer/django-appointment/actions/runs/41734459958): Ran 587, OK (skipped=3), from the job log |

CI and Devin Review results for the final PR head are recorded in the [PR description](https://github.com/raffimaurer/django-appointment/pull/10). They are not
repeated here, because adding them would need another docs commit.

## Regression coverage

The seven acceptance tests in `appointment/tests/test_incident_reschedule.py` are unchanged. I added
[`appointment/tests/test_inc2_reschedule_block_regression.py`](https://github.com/raffimaurer/django-appointment/blob/09e531009bf86c016c31cfb1cfba7cf384e0f72d/appointment/tests/test_inc2_reschedule_block_regression.py)
with 11 tests:

- **Rejected with no side effects** (exact, containing, inside, and start-overlapping blocks). Each test checks for
  HTTP 409 and the user-facing message. It also checks that the `AppointmentRequest` date, times and staff are
  unchanged, and that every pending-history field is unchanged (date, times, staff, status, reason). Finally it
  checks that `mail.outbox` is empty (real notification path, not mocked), the thank-you session key is not set,
  and no success message was added.
- **Positive control**: an unblocked confirmation sends mail, which shows the no-email check is meaningful.
- **Still allowed**: an adjacent block before the slot (09:00–10:00), a same-staff block on another date, and a block
  on the appointment's original slot.
- **Re-validation after the block is removed**: a rejected link confirms once the block is deleted.
- **Expiry**: an expired link with a block returns 404 and changes nothing.
- **Replay**: a link that was already confirmed returns 404 when reused after a block, and nothing changes again.

The first four, plus the re-validation test, failed before the fix. The rest pass on both base and fix and guard
against over-correction.

## Related-risk probes (timeboxed, about 10 minutes)

Script: [`probe_related_risks.py`](https://github.com/raffimaurer/django-appointment/blob/devin/1793746272-inc-2-confirm-reschedule-blocked-hour/demo/evidence/INC-2/probe_related_risks.py). Actual output:
[`probe-output.txt`](https://github.com/raffimaurer/django-appointment/blob/devin/1793746272-inc-2-confirm-reschedule-blocked-hour/demo/evidence/INC-2/probe-output.txt). These probes sit outside
`manage.py test appointment` discovery.

| Probe | Status | Observation |
| --- | --- | --- |
| P1 | Reproduced | `reschedule_appointment_submit` accepts an already-blocked hour, creates a pending row and emails a link. Confirmation of that link is now rejected. |
| P2 | Reproduced | Confirmation still succeeds after a `DayOff` is added for that date. |
| P3 | Reproduced | Confirmation still succeeds into a slot that another client has since booked with the same staff member. |
| P4 | Reproduced | Confirmation still succeeds after the staff member's working hours for that weekday are removed. |
| P5 | Not a risk | Slot listing still offers 09:00 and 11:00 next to a 10:00–11:00 block. |
| P6 | Reproduced (Review finding) | With `reschedule_limit=1`, a rejected confirmation keeps its pending row, which still counts toward the 5-minute limit. `prepare_reschedule_appointment` returns 403 for up to 5 minutes. |
| Concurrency | Suspected, unverified | Review finding: a block saved between the check and the writes is not seen. SQLite serialises writes, so the test suite cannot verify or rule this out. |

P2–P4 are the same class of problem: commit does not re-validate against current availability. They were left
out of this narrow fix on purpose.

## Review outcome

Devin Review on `09e5310` raised two findings. Both are escalated as `needs_human` and remain open:

1. **Concurrent block between check and write (bug).** This is valid in principle. A real fix needs locking or a
   constraint shared with the `Unavailability` writer, which is a broader design change and cannot be verified on
   SQLite.
2. **Rejected link locks rescheduling for up to 5 minutes when `reschedule_limit` is low (bug).** Reproduced by P6.
   The obvious fixes are to change the pending row's status or delete it, or to change how
   `can_appointment_be_rescheduled` counts rows. Either would break the issue's requirement to preserve every
   pending-history field, or would change rate-limit semantics. A human needs to decide.

There were no automatic or human-directed corrections at the time of writing. The final-head state is in the
PR description.

## Remaining risks

- P2–P4 above (DayOff, double booking, working-hours changes at commit time).
- P6 lock-out window and the user-facing message promising "choose another time".
- Check-then-write race (unverified).
- The 409 page reuses `404_not_found.html`, so its HTML title still reads "Page not found | 404" (cosmetic).

## Proposed follow-ups (not filed)

1. Re-validate the full availability (DayOff, working hours, overlapping appointments) at confirmation, and
   ideally at submission, using one shared helper.
2. Decide how a rejected confirmation should affect the reschedule limit, for example a distinct terminal status.
   This needs a product decision.
3. Evaluate transactional locking for confirm and block writes on the production database engine.

Procedure note for human review (the Skill was not changed): the Skill could suggest checking how preserved
pending rows interact with `can_appointment_be_rescheduled` limits.
