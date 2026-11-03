# INC-8: reschedule confirmation for a deleted appointment changes records, then fails

> Synthetic rehearsal. All data is synthetic. Nothing was deployed and there was no production recovery.
> No customer or organisational affiliation is claimed.

| | |
|---|---|
| Issue | [raffimaurer/django-appointment#8](https://github.com/raffimaurer/django-appointment/issues/8) |
| Pull request | [#11 (draft, unmerged)](https://github.com/raffimaurer/django-appointment/pull/11), base `demo/stable` |
| Base commit | [`47a7917c810f3965a96f979f7f32f20b475b102b`](https://github.com/raffimaurer/django-appointment/commit/47a7917c810f3965a96f979f7f32f20b475b102b) (INC-2 repair + `demo-verify` trigger for `demo/stable`) |
| Regression tests commit | [`2c20b4053a1a1f29e0ba2977540aeb86617e31d4`](https://github.com/raffimaurer/django-appointment/commit/2c20b4053a1a1f29e0ba2977540aeb86617e31d4) |
| Fix commits | [`df96eb4cff7ebc891d5f3547afc73a3a0ff5fbd1`](https://github.com/raffimaurer/django-appointment/commit/df96eb4cff7ebc891d5f3547afc73a3a0ff5fbd1), review fix [`28b2d7950eee8721f94bf070499b7603af326b83`](https://github.com/raffimaurer/django-appointment/commit/28b2d7950eee8721f94bf070499b7603af326b83) |
| Evidence commit | [`89a04faed3c87804c9d3ecb9e963292d85bbb8ed`](https://github.com/raffimaurer/django-appointment/commit/89a04faed3c87804c9d3ecb9e963292d85bbb8ed), [`demo/evidence/INC-8/`](https://github.com/raffimaurer/django-appointment/blob/devin/1793746268-inc-8-orphaned-reschedule-confirmation/demo/evidence/INC-8/README.md) |
| Incident index | [docs/incidents/README.md](https://github.com/raffimaurer/django-appointment/blob/devin/1793746268-inc-8-orphaned-reschedule-confirmation/docs/incidents/README.md) |
| Procedure | `.agents/skills/scheduling-incident-investigation/SKILL.md` at the base commit, used as guidance. Unchanged. |
| Related | Draft [#9](https://github.com/raffimaurer/django-appointment/pull/9) is an earlier, separate attempt at the same issue. This run did not reuse its code. A human should keep one. |

## Symptom (synthetic)
A client requests a reschedule, then the `Appointment` row is deleted while the `AppointmentRequest` and the pending
`AppointmentRescheduleHistory` survive. Opening the emailed confirmation link within the 5-minute window returned a
server error (`Appointment.DoesNotExist`), yet the request had already moved to the new time and the history was
marked `confirmed`. The expected behaviour (from the issue): a clear message, both records unchanged, no notifications.
Normal confirmation and the INC-2 blocked-time rejection must keep working.

## Reproduction (before any production edit)
Environment: Python 3.12.16 (`.venv`, `demo-requirements.lock`), `DJANGO_SETTINGS_MODULE=appointments.demo_settings`,
SQLite, locmem mail. `manage.py check`, `makemigrations appointment` and `migrate` ran first; migrations were not committed.

| Run | New INC-8 tests (7) | INC-2 tests (14) | `manage.py test appointment` |
|---|---|---|---|
| Base `47a7917` | n/a | 14 passed | `Ran 583 tests` `OK (skipped=3)`: 580 passed, 0 failed, 3 skipped |
| Tests only, `2c20b40` | 4 passed, 1 failed, 2 errors | 14 passed | `Ran 590 tests` `FAILED (failures=1, errors=2, skipped=3)`: 584 passed |
| Fix `df96eb4` | 7 passed | 14 passed | `Ran 590 tests` `OK (skipped=3)`: 587 passed, 0 failed, 3 skipped |
| Review fix `28b2d79` | 7 passed | 14 passed | `Ran 590 tests` `OK (skipped=3)`: 587 passed, 0 failed, 3 skipped |

The two errors are the reported `Appointment.DoesNotExist` from `confirm_reschedule`; the failure is the partial write
(request moved although the history write failed). The probe `test_confirm_after_appointment_deleted_issue_8` prints
the surviving rows on base: request moved to the new date/time, history `['confirmed']`
([base output](https://github.com/raffimaurer/django-appointment/blob/devin/1793746268-inc-8-orphaned-reschedule-confirmation/demo/evidence/INC-8/probe-output-base-47a7917.txt)).
The 3 skips are the pre-existing Django-Q tests, unchanged throughout.

## Cause
In `confirm_reschedule` the order was: expiry/status check → INC-2 unavailability check → write `AppointmentRequest`
→ write history (`confirmed`) → `Appointment.objects.get(appointment_request=ar)` for the client name → notify →
thank-you session grant. The appointment was first read *after* both writes, and the view is not atomic
(`ATOMIC_REQUESTS` is off), so the lookup's exception left the writes committed.

## Repair
```python
with transaction.atomic():
    appointment = Appointment.objects.select_for_update().filter(appointment_request=ar).first()
    if appointment is None:
        return render(..., status=404)   # "Sorry, this appointment no longer exists, so it can't be rescheduled."
    ar.save(update_fields=[...]); reschedule_history.save(update_fields=[...])   # unchanged logic
messages.success(...); notify_admin_about_reschedule(...); allow_thank_you_page(request, appointment)
```

- The appointment is looked up before any write; a missing appointment returns a 404 with a user-safe message, writes
  nothing, sends nothing and grants no thank-you session or success message.
- The two writes are atomic, so a failure part-way cannot leave the request moved with the history still pending.
- Notifications and the session grant run only after the transaction commits.
- The expiry, replay and INC-2 blocked-time checks are unchanged and still run first.

## Regression coverage
`appointment/tests/test_reschedule_confirmation_deleted_appointment.py` (+7, no existing test changed):

| Test | Case | Before fix |
|---|---|---|
| `test_deleted_appointment_rejected_without_changes` | deleted appointment: 404, every field of both rows unchanged, no mail, notify not called, no session key, no messages | ERROR |
| `test_reopening_link_after_deletion_still_rejected` | link opened twice after deletion | ERROR |
| `test_failed_history_write_rolls_back_request_move` | history write raises `DatabaseError`: request not moved, notify not called | FAIL |
| `test_deleted_appointment_with_expired_link_reports_expiry` | deletion + expired link: expiry message, no changes | ok |
| `test_deleted_appointment_with_blocked_time_rejected` | deletion + INC-2 block: rejected, no changes | ok |
| `test_existing_appointment_still_confirms` | normal confirmation: 302, moved, confirmed, notified with client name, session grant | ok |
| `test_replay_after_confirmation_rejected` | second click after success: 404, no second notification | ok |

## Remaining risks (10-minute timebox)
From [`probe_related_risks.py`](https://github.com/raffimaurer/django-appointment/blob/devin/1793746268-inc-8-orphaned-reschedule-confirmation/demo/evidence/INC-8/probe_related_risks.py),
same result on base and fix ([fix output](https://github.com/raffimaurer/django-appointment/blob/devin/1793746268-inc-8-orphaned-reschedule-confirmation/demo/evidence/INC-8/probe-output-fix-df96eb4.txt)). None fixed here.

- **Reproduced:** client user deleted (`Appointment.client` is `SET_NULL`) → confirm commits the move, then
  `client.get_full_name()` raises `AttributeError` (500).
- **Reproduced:** target staff member deleted (history `staff_member` is `SET_NULL`) → confirm returns 302 and sets the
  request's `staff_member` to `None`.
- **Reproduced:** reschedule submit after the appointment is deleted → a `pending` history row is created, then
  `DoesNotExist` (500).
- **Unverified:** a deletion committing during the confirmation. The row lock should serialise it on PostgreSQL/MySQL,
  but SQLite ignores `select_for_update`, so no concurrency claim is made. Replay races (two simultaneous clicks) are
  also unverified; the status check is still outside the lock.

## Proposed follow-ups (not created)
1. Decide what confirmation should do when the client user or target staff member has been deleted, and test it.
2. Make `reschedule_appointment_submit` check the appointment exists before creating the pending row.
3. Make confirmation idempotent under concurrency (lock or conditional `pending → confirmed` update) and verify on PostgreSQL.

## Review outcome
| Commit reviewed | Finding | Handling |
|---|---|---|
| `89a04fa` | **Bug:** *PostgreSQL rejects every reschedule confirmation.* The first fix used `select_for_update().select_related('client')`; `Appointment.client` is nullable, and PostgreSQL refuses `FOR UPDATE` on the nullable side of an outer join (documented Django restriction). | **Automatic correction (accepted):** fixed in [`28b2d79`](https://github.com/raffimaurer/django-appointment/commit/28b2d7950eee8721f94bf070499b7603af326b83) by dropping `select_related('client')`; the client loads lazily after commit. Supported by documentation; **not run on PostgreSQL** (no server available here, and SQLite ignores row locks). |

- Human-directed corrections: none.
- Advisory notes and unresolved findings, and the review of the final head: see the
  [PR #11 description](https://github.com/raffimaurer/django-appointment/pull/11).

## Hosted CI
| Head | Run | Result | Evidence |
|---|---|---|---|
| [`89a04fa`](https://github.com/raffimaurer/django-appointment/commit/89a04faed3c87804c9d3ecb9e963292d85bbb8ed) (fix + evidence) | [demo-verify 41734715457](https://github.com/raffimaurer/django-appointment/actions/runs/41734715457) | success | Job log: `Ran 590 tests` / `OK (skipped=3)`, no `FAIL:`/`ERROR:` lines, all 21 INC-8 and INC-2 tests `ok`, the 3 Django-Q skips. Artifact `test-output` (13278561413) not downloaded: its blob storage host is not reachable from this session. CodeQL passed. |

Later commits (the review fix and this report) are recorded in the PR description and the issue handoff.

## Limitations
Local SQLite and Django test client only; no browser testing (server-side change). This file cannot record CI for
the commit that adds it; final-head results are in the PR description and the issue handoff.
