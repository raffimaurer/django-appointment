# INC-8 related-risk probe evidence

> Synthetic data only. This is evidence, not part of the normal test suite. Existing tests are not changed.

## What this shows
`probe_related_risks.py` removes a related record while a reschedule is pending (or before it is submitted), then
calls the affected view and prints the surviving rows. The assertions describe the desired behaviour, so a FAIL is
evidence of a defect, not a regression.

| Probe | Changed state | Base `47a7917` | Fix `df96eb4` | Status |
|---|---|---|---|---|
| `test_confirm_after_appointment_deleted_issue_8` | `Appointment` deleted, then confirm (issue #8) | unhandled `DoesNotExist`; request moved, history `confirmed` | 404; request unchanged, history `pending` | **Fixed** by this PR |
| `test_confirm_after_client_user_deleted` | client user deleted (`Appointment.client` is `SET_NULL`), then confirm | unhandled `AttributeError` after the request moved and history was `confirmed` | same | **Reproduced, not fixed** |
| `test_confirm_after_target_staff_member_deleted` | target `StaffMember` deleted (history `staff_member` is `SET_NULL`), then confirm | 302; request `staff_member` set to `None` | same | **Reproduced, not fixed** |
| `test_submit_after_appointment_deleted` | `Appointment` deleted, then reschedule submit | unhandled `DoesNotExist` after a `pending` history row was created | same | **Reproduced, not fixed** |

Not probed: a deletion that commits *during* a confirmation (between the lookup and the writes). The fix locks the
appointment row with `select_for_update()` inside `transaction.atomic()`, but SQLite ignores row locks and serialises
writes, so that protection is **unverified** here.

## Provenance
- `probe-output-base-47a7917.txt`: actual output on `demo/stable` @ `47a7917c810f3965a96f979f7f32f20b475b102b`
  (probe file copied into a clean worktree).
- `probe-output-fix-df96eb4.txt`: actual output on fix commit `df96eb4cff7ebc891d5f3547afc73a3a0ff5fbd1`.
- Python 3.12.16, `demo-requirements.lock`, `appointments.demo_settings`, SQLite. Migration lines removed and absolute
  paths shortened (`<repo>`, `<venv>`, `<python>`). Dates are relative to the run day (today + 6/7 days).

## Reproduce
```bash
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py makemigrations appointment   # output is git-ignored
.venv/bin/python manage.py test demo/evidence/INC-8 --pattern='probe_*.py' -v 2
# on the fix: Ran 4 tests, FAILED (failures=3); the issue #8 probe passes
```

## Why it stays out of the green suite
`demo-verify` runs `manage.py test appointment`, which only discovers tests inside the `appointment` package. This
directory has no `__init__.py` and the file is not named `test*.py`.
