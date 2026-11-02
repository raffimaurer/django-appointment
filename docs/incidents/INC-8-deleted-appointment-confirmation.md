# INC-8: reschedule confirmation changes records after the appointment was deleted

> Synthetic rehearsal. All data is synthetic. Nothing was deployed and there was no production recovery.
> No customer or organisational affiliation is claimed. No confirmation IDs, tokens or personal data appear here.

| | |
|---|---|
| Issue | [raffimaurer/django-appointment#8](https://github.com/raffimaurer/django-appointment/issues/8) |
| Pull request | [#9 (draft, unmerged)](https://github.com/raffimaurer/django-appointment/pull/9), base `demo/stable` |
| Base commit | [`47a7917c810f3965a96f979f7f32f20b475b102b`](https://github.com/raffimaurer/django-appointment/commit/47a7917c810f3965a96f979f7f32f20b475b102b) (`demo/stable`) |
| Fix commit | [`de786f06afd554dbe42c39308b78aad0d8b9d1cc`](https://github.com/raffimaurer/django-appointment/commit/de786f06afd554dbe42c39308b78aad0d8b9d1cc) |
| Tested code commit (hosted CI) | [`6b527e4f152bb63de1054061a3a52b8c8b245537`](https://github.com/raffimaurer/django-appointment/commit/6b527e4f152bb63de1054061a3a52b8c8b245537) (fix plus evidence probes) |
| Hosted CI | [demo-verify run 41547423337](https://github.com/raffimaurer/django-appointment/actions/runs/41547423337), [job log](https://github.com/raffimaurer/django-appointment/actions/runs/41547423337/job/125626308704) |
| Evidence | [demo/evidence/INC-8/](https://github.com/raffimaurer/django-appointment/blob/devin/1793662771-inc-8-deleted-appointment-confirmation/demo/evidence/INC-8/README.md) |
| Incident index | [docs/incidents/README.md](https://github.com/raffimaurer/django-appointment/blob/devin/1793662771-inc-8-deleted-appointment-confirmation/docs/incidents/README.md) |
| Procedure | `.agents/skills/scheduling-incident-investigation/SKILL.md` as it exists at the base commit. The Skill was not changed. |

## How the base was prepared

At the maintainer's instruction, `demo/stable` was created from the approved INC-2 repair commit
[`595d41a`](https://github.com/raffimaurer/django-appointment/commit/595d41a5ff5a35c4cfed7bee963528a2b3c612af) (PR [#6](https://github.com/raffimaurer/django-appointment/pull/6) head). One commit,
[`47a7917`](https://github.com/raffimaurer/django-appointment/commit/47a7917c810f3965a96f979f7f32f20b475b102b), changed only `.github/workflows/demo-verify.yml` so that
`pull_request` also triggers for `demo/stable`. Triggers, permissions, logs, the summary and exit status are otherwise unchanged.
No INC-8 code came from PR #6 or any earlier branch.

## Symptom and impact (synthetic)

A client requested a reschedule. Before they opened the confirmation link (5-minute window), the `Appointment` record was deleted.
The `AppointmentRequest` and the pending `AppointmentRescheduleHistory` were left in place. Opening the link returned an HTTP 500.
By then the request had already moved to the new time and the history row was marked `confirmed`. The illustrative impact is
an orphaned request showing a reschedule that never completed, plus a confusing error for the client. This impact is part of the
rehearsal scenario and was not observed in production.

## Reproduction (Skill §1-§2)

Environment: Python 3.12.16 (`.venv`), `demo-requirements.lock`, `DJANGO_SETTINGS_MODULE=appointments.demo_settings`, SQLite and the
locmem mail backend. `manage.py check`, `makemigrations appointment` and `migrate --noinput` ran first. The generated migrations
were not committed.

1. Stable baseline (`47a7917`, before any INC-8 change). The existing blocked-time tests pass:

    ```
    manage.py test appointment.tests.test_incident_reschedule appointment.tests.test_reschedule_confirmation_revalidation
    Ran 14 tests  OK
    manage.py test appointment
    Ran 583 tests  OK (skipped=3)
    ```

2. Issue symptom, observed with the [probe](https://github.com/raffimaurer/django-appointment/blob/devin/1793662771-inc-8-deleted-appointment-confirmation/demo/evidence/INC-8/probe-output-before.txt) on the unrepaired base:

    ```
    OBSERVED issue: status=500 request_moved=True history_status=confirmed notify_calls=0
    ```

    `notify_admin_about_reschedule` was not reached because the exception happened first. `ATOMIC_REQUESTS` is off, so the writes were kept.

3. The new regression tests were written first and run against the unrepaired base:
   `Ran 7 tests`, `FAILED (failures=2)` (`AssertionError: 500 != 404` in both).

## Root cause (Skill §3)

- **Offer and hold** were unaffected: the reschedule was offered and the pending history row was created normally.
- **Commit:** `confirm_reschedule` checked status and expiry, then re-checked unavailability (INC-2). It then wrote the new
  date/time/staff to the `AppointmentRequest` and saved the history as `confirmed`. Only after that did it call
  `Appointment.objects.get(appointment_request=ar)` for the client name. A deleted appointment raised `DoesNotExist` after the writes.
  The view never checked that the booking it was confirming still existed before mutating related rows.

## Fix (Skill §5)

`confirm_reschedule` now loads the `Appointment` (with `select_related('client')`) after the existing expiry/status and
availability checks, and **before** any write. If it no longer exists, the view renders the existing error page with HTTP **404** and a
clear message: "The appointment for this reschedule request no longer exists." It does not write to the request or the history, sends
no notification or email, adds no success message, and does not grant the thank-you session key. On success the same `appointment` object
is reused for the notification, the thank-you grant and the redirect. Nothing else changed.

### Prevention principle

**Revalidate mutable state at confirmation, before changing data or sending notifications.** INC-2 applied this to availability.
INC-8 shows it also applies to the existence of the booking being confirmed: anything that can change while a request is held
(blocks, days off, other bookings, the appointment itself, the staff member) must be checked before the first write. Otherwise a late
failure leaves partial changes behind.

## Tests (Skill §7)

| Run | Commit | New INC-8 tests | Existing blocked-time tests (7 + 7) | Full suite |
|---|---|---|---|---|
| Baseline, local | `47a7917` | n/a | 14 run: 14 passed | 583 run: 580 passed, 0 failed, 3 skipped |
| New tests on unrepaired code, local | `47a7917` + test file | 7 run: 5 passed, 2 failed | 14 run: 14 passed | 590 run: 585 passed, 2 failed, 3 skipped |
| After fix, local | `de786f0` | 7 run: 7 passed | 14 run: 14 passed | 590 run: 587 passed, 0 failed, 3 skipped |
| After fix, hosted demo-verify | `6b527e4` | 7 run: 7 passed | 14 run: 14 passed | 590 run: 587 passed, 0 failed, 3 skipped |

- Raw runner lines after the fix: `Ran 590 tests` / `OK (skipped=3)`, both locally and in the hosted job log.
- The 3 skips are the same in every run, all `'Django-Q is not available'`: `DjangoQUnavailableTest.test_placeholder` and the
  `setUpClass` of `ScheduleEmailReminderTest` and `UpdateAppointmentReminderTest`.
- **Hosted evidence source:** the [job log](https://github.com/raffimaurer/django-appointment/actions/runs/41547423337/job/125626308704) of run 41547423337 on `6b527e4` shows
  `Ran 590 tests`, `OK (skipped=3)`, 3 Django-Q skip lines, no `FAIL:`/`ERROR:` lines, and all 7 INC-8 and 7 INC-2 acceptance tests `ok`.
  The `test-output` artifact (ID 13189865279) was uploaded but **could not be downloaded**: the session's network policy blocks the
  artifact blob host. That is a blocked download, not a test failure.
- All seven original acceptance tests (`appointment/tests/test_incident_reschedule.py`) and every other existing test are unchanged.

### Regression tests and how they prevent recurrence

All are in `appointment/tests/test_reschedule_confirmation_missing_appointment.py` (+7). Each rejection test snapshots every concrete field of the
`AppointmentRequest` and the pending history row, and asserts no notify call, an empty `mail.outbox`, and no thank-you session key.
The client uses `raise_request_exception=False`, so a regression shows up as a failed assertion on a 500 rather than a crash.

- `test_deleted_appointment_rejected_without_side_effects`: the issue scenario. It expects a 404 with "no longer exists" and no success message,
  and fails if any write, notification or session grant happens before the existence check.
- `test_deleted_appointment_link_stays_rejected_on_retry`: a second click is still rejected and still has no side effects.
- `test_deleted_appointment_rejected_even_when_slot_is_blocked`: both guards present at once. Either rejection is accepted, and nothing changes.
- `test_normal_confirmation_still_moves_and_notifies_once`: the happy path still moves the request, confirms the history, notifies once and grants the thank-you page.
- `test_replayed_confirmation_rejected_without_second_notification`: replay after success gets a 404 and no second notification.
- `test_expired_link_rejected_without_side_effects`: an expired link gets a 404 "no longer valid" and nothing changes.
- `test_unknown_link_rejected_without_side_effects`: an unknown ID gets a 404 and nothing changes.

The 14 INC-2 tests keep the availability fix covered.

## Review findings and handling

| Finding | Source | Commit reviewed | Handling |
|---|---|---|---|
| [Concurrent deletion confirms a canceled appointment](https://github.com/raffimaurer/django-appointment/pull/9#discussion_r4449128469) (bug) | Devin Review | `6b527e4` | **Open, escalated to a human** ([reply](https://github.com/raffimaurer/django-appointment/pull/9#discussion_r4449148856)). |

The race is plausible. If the appointment is deleted *between* the new lookup and the writes, the request can still move and a
notification can still go out. It was not reproduced. SQLite (the only configured database) serialises writes and ignores
`select_for_update`, so a lock-based fix can't be verified in this environment. A correct fix (`transaction.atomic` with row locks on
the history and appointment) would also cover the INC-2 availability check and replay windows, which goes beyond this narrow incident.
It is proposed as follow-up 2.

### Corrections: automatic vs human-directed

- **Automatic corrections:** none. Auto-Fix is enabled for this repository, and the finding was delivered to this session for triage.
  It was escalated rather than auto-fixed, so Auto-Fix made no code change.
- **Human-directed corrections:** none to the fix code. At the maintainer's direction, the base `demo/stable` was prepared (the workflow
  trigger change only). Also at their direction, the finding was re-assessed on its merits rather than waiting for a green check.
- **Advisory notes:** none received besides the finding above.

## Remaining risks (Skill §9, 10-minute timebox)

Reproduced with [probes](https://github.com/raffimaurer/django-appointment/blob/devin/1793662771-inc-8-deleted-appointment-confirmation/demo/evidence/INC-8/README.md) (`probe-output-after.txt` shows them still failing after the fix):

1. **Reproduced defect, reschedule submit after deletion:** `reschedule_appointment_submit` creates a pending history row *before*
   `Appointment.objects.get(...)`. With the appointment deleted it returns a 500 and leaves an orphaned pending row (no email sent).
2. **Reproduced defect, target staff member deleted while pending:** the history's `staff_member` becomes `NULL`
   (`on_delete=SET_NULL`). Confirmation then succeeds (302), sets the request's `staff_member` to `None` and notifies.

Inspection only (not reproduced):

3. **Concurrency:** the Review finding above, plus the same check-then-write pattern for availability and replay. Unverified on SQLite.
4. `Appointment.client` is `SET_NULL`. A confirmation for an appointment whose client user was deleted would fail at
   `appointment.client.get_full_name()`, which is after the writes.
5. `notify_admin_about_reschedule` (`email_ops.py`) does its own `Appointment.objects.get`. It is safe after this fix, but fragile.

## Proposed prevention follow-ups (prioritised; not created)

1. Move every existence and validity check (appointment, client, target staff member) ahead of the first write in both
   `reschedule_appointment_submit` and `confirm_reschedule`. Add regression tests for risks 1, 2 and 4.
2. Make confirmation atomic: wrap the checks and writes in `transaction.atomic` with `select_for_update` on the history and appointment rows,
   and verify on PostgreSQL (resolves the Review finding).
3. Defer notifications with `transaction.on_commit`, so a later failure can never notify about a change that was rolled back.

## Proposed Skill updates (for human review; the Skill is unchanged and this is not approved policy)

- §3 "Trace the whole flow": add that the *existence* of every related row the commit depends on (appointment, client, staff) is mutable
  state, not only availability.
- §5 "Rejection must be side-effect free": add "perform all reads that can fail before the first write". Note that `ATOMIC_REQUESTS` is
  off, so a late exception keeps earlier writes.
- §7 "Tests": suggest `Client(raise_request_exception=False)` for negative tests, so a 500 is a clear assertion failure.

## Limitations

- SQLite only, single process. No concurrency was tested and none is claimed.
- The hosted artifact couldn't be downloaded (blocked blob host). The job log was used as the authoritative hosted evidence.
- The 404 page reuses the "404"-titled template, the same as the existing invalid-link path.
- Reports are on an unmerged draft branch, and the docs site was not published.

## Final verification status

The hosted CI recorded above is for the tested code commit `6b527e4`. This report was added afterwards in a documentation-only commit.
The current-head `demo-verify` and Devin Review results are recorded in the [PR #9](https://github.com/raffimaurer/django-appointment/pull/9) description and the final
[issue #8](https://github.com/raffimaurer/django-appointment/issues/8) comment. As of writing, the Devin Review finding above remains **open** pending a human decision.

## Human decision checklist

1. Inspect exact-head `demo-verify` and Devin Review on [PR #9](https://github.com/raffimaurer/django-appointment/pull/9).
2. Decide on the open Review finding and the remaining risks above (accept, or require follow-ups first).
3. Approve or request changes on the draft PR.
4. Then follow the team's release and post-release verification process. None of these steps has happened.
