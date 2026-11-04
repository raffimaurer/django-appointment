# INC-2: Stale reschedule confirmation accepts a blocked hour

!!! note "Synthetic rehearsal"
    All data is synthetic. No real customer, patient or NHS relationship is asserted, and nothing was deployed.
    This is a local and CI rehearsal, not a production outage or recovery.

| | |
| --- | --- |
| Issue | [#2](https://github.com/raffimaurer/django-appointment/issues/2) |
| Pull request | [#13](https://github.com/raffimaurer/django-appointment/pull/13) (draft, targets `demo/ready`) |
| Base | `demo/ready` @ [`757f2517de2d1728f211f8890939d8800fd39051`](https://github.com/raffimaurer/django-appointment/commit/757f2517de2d1728f211f8890939d8800fd39051) |
| Environment | Python 3.12.16 (local), 3.12.15 (hosted); `demo-requirements.lock` (installed versions matched); `DJANGO_SETTINGS_MODULE=appointments.demo_settings`; SQLite; locmem email |

## Symptom

A client asks to move an appointment to 10:00–11:00 on a future date, which creates a pending
`AppointmentRescheduleHistory` row and emails a confirmation link that stays valid for 5 minutes. Then the
practitioner adds an `Unavailability` covering that hour. A fresh availability lookup hides the hour. But if the
client follows the original link within the 5 minutes, the appointment still moves into the blocked hour, the admin is
notified and the thank-you page is unlocked.

Expected: a 400/409 rejection for a same-staff, same-date overlap. Every appointment and pending-history field stays
as it was, and no success notification goes out. Valid reschedules, adjacent intervals and blocks for a different
staff member or date must still be allowed.

## Reproduction (before any production edit)

```bash
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations appointment   # git-ignored
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py test appointment.tests.test_incident_reschedule -v 2
.venv/bin/python manage.py test appointment
```

| Run (base `757f251`) | Result |
| --- | --- |
| Incident acceptance tests | `Ran 7 tests`, `FAILED (failures=3)` |
| Full suite | `Ran 576 tests`, `FAILED (failures=3, skipped=3)` |

The three failures were exactly the expected acceptance tests:
`test_confirmation_rejects_new_block_without_mutation`, `test_partial_overlap_rejected` and
`test_real_submit_then_block_then_confirm`. There were no other baseline failures.

## Cause

The slot goes through three steps: **offer**, **hold** and **commit**.

- **Offer:** `get_available_slots_for_staff` excludes unavailabilities, so a fresh lookup is correct.
- **Hold:** `reschedule_appointment_submit` creates the pending row and emails the link. It does not re-check
  availability (see the risks below).
- **Commit:** `confirm_reschedule` only checked `reschedule_status == 'pending'` and `still_valid()` (the 5-minute
  window). It then copied the pending date, times and staff onto the `AppointmentRequest`, so it trusted state that was
  true when the request was made and never checked the current `Unavailability` rows.

## Repair

Commit [`c83ff48`](https://github.com/raffimaurer/django-appointment/commit/c83ff487bd1a53ce28a13dad69c7948927c141f6):

- New `unavailability_overlaps(staff_member, date, start_time, end_time)` in `appointment/utils/db_helpers.py`.
  It uses half-open `[start, end)` semantics: `start_time__lt=end` and `end_time__gt=start`. The existing
  `get_unavailabilities_for_date_and_time` was not reused, because its `lte`/`gte` filter treats touching
  boundaries as overlaps and would reject an adjacent block.
- `confirm_reschedule` calls it after the existing expiry and replay guards and before any mutation. The check uses
  the pending row's **target** staff member and date. When the hour overlaps, the view returns **409** with a
  user-safe message ("this time is no longer available") on the existing generic error template. It does not save
  anything, call `notify_admin_about_reschedule`, add a success `messages` entry or set the thank-you session key.
- The pending row stays `pending`. If the block is removed within the 5-minute window, the same link confirms. A
  confirmed link is still not replayable, and an expired link still returns 404 even when a block exists.

## Regression coverage

New file `appointment/tests/test_reschedule_confirm_unavailability.py` has 12 tests, added in
[`d8eb417`](https://github.com/raffimaurer/django-appointment/commit/d8eb417011ba7eb236765942cedb0b0dbc291ab2) and adjusted in
[`e2b4c3c`](https://github.com/raffimaurer/django-appointment/commit/e2b4c3c5714c6b970da3dff898476851f5cb2fa0). The 7 existing acceptance tests are unchanged.

| Behaviour | Before fix | After fix |
| --- | --- | --- |
| Full overlap: 409; AR, pending-history and Appointment rows unchanged (all columns, including `updated_at`); no notify, no email, no success message, no thank-you session key | FAIL | ok |
| Enclosing block, inner block, block overlapping the start by 1 minute | FAIL ×3 | ok |
| Block on the **target** staff member when moving to another staff member | FAIL | ok |
| Rejected link replayed: still 409, still side-effect free | FAIL | ok |
| Block removed within the window: same link confirms | FAIL | ok |
| Block ending exactly at 10:00 (adjacent) allowed | ok | ok |
| Same staff, other date allowed | ok | ok |
| Block on the *previous* staff member does not reject a move to a new staff member | ok | ok |
| Expired link with a block: 404, no mutation | ok | ok |
| Confirmed link replayed after a new block: 404, not re-applied | ok | ok |

Before the fix, run against the base production code with only the new tests applied: `Ran 12 tests`,
`FAILED (failures=7)`.

Commit `e2b4c3c` removed an assertion that the confirmation ID is absent from the response body. The demo base
template echoes the request path in the language switcher's hidden `next` field on every page, so the assertion
tested something other than this fix. Its failure message also printed the synthetic ID into test output.

### After the fix (local)

| Run | Result |
| --- | --- |
| Incident tests + new regression tests | `Ran 19 tests`, `OK` |
| Full suite | `Ran 588 tests`, `OK (skipped=3)` |

### Hosted demo-verify

- [Run 41857170213](https://github.com/raffimaurer/django-appointment/actions/runs/41857170213) at `c83ff48`: `verify` job succeeded, all steps green.
- [Run 41857260636](https://github.com/raffimaurer/django-appointment/actions/runs/41857260636) at `8330ad9`: `Ran 588 tests`, `OK (skipped=3)` on Python 3.12.15.
  This was read from the job log.
- The result at the final head is recorded in the PR description, not here.

## Related-risk audit (timeboxed)

Probes are in [`demo/evidence/INC-2/`](https://github.com/raffimaurer/django-appointment/tree/fb07472985039f0e3b55a51a91e1e02695b60ea5/demo/evidence/INC-2)
([script](https://github.com/raffimaurer/django-appointment/blob/fb07472985039f0e3b55a51a91e1e02695b60ea5/demo/evidence/INC-2/probe_related_risks.py),
[output](https://github.com/raffimaurer/django-appointment/blob/fb07472985039f0e3b55a51a91e1e02695b60ea5/demo/evidence/INC-2/probe_output.txt)). They live outside
`appointment/`, so normal test discovery does not run them. Each probe records the observed behaviour and does not
assert the desired one.

**Reproduced** (probe shows it; not fixed here):

1. A **day off** added after the request is ignored at confirm time: 302, and the appointment moves.
2. **Another booking** for the same staff member and hour is ignored at confirm time: 302, and the appointment moves
   onto it.
3. **Submit into an already-blocked hour** still creates a pending row and sends a confirmation link. The new check
   rejects the later confirm, but the client gets a link that cannot succeed.
4. A pending row whose **`staff_member` is null** (the staff member was deleted, `SET_NULL`) skips the check and
   confirms. The appointment request's staff member becomes null.
5. With **`reschedule_limit=1`**, a 409-rejected pending row still counts in `can_appointment_be_rescheduled` for 5
   minutes, so the client cannot pick another time straight away. Devin Review raised this independently.

**Suspected or unverified:**

- **Check-then-write race:** a block committed between `unavailability_overlaps` and the save would not be caught.
  This is unverified. SQLite serialises writes, so no concurrency claim is made. Devin Review raised this
  independently.
- **Working-hours removal** after the request is not checked at confirm time. This is from code reading only and was
  not probed.
- **Admin/staff-side edits** of appointments were not inspected within the timebox.

**Advisory:**

- The 409 response reuses `error_pages/404_not_found.html`, which has a "404" title and graphic. That template already
  serves the invalid-link case, but a dedicated conflict template would read better.
- The confirmation ID appears in the page's language-switcher `next` field. This is pre-existing, applies to every
  page, and the ID is the same one already in the URL.

## Review outcome

- **Devin Review on `8330ad9`:** 2 findings (the race and limit consumption above). Both are **escalated** for a
  human and left open. The race needs a locking design across both write paths and a row-locking database to verify.
  The limit behaviour is a product decision, because the issue requires the pending row to be preserved.
- **CodeQL on `8330ad9`:** 1 high alert, "Clear-text logging of sensitive information", on the probe's `print`.
  The probe output only ever contained synthetic status flags. **Automatic correction** in
  [`fb07472`](https://github.com/raffimaurer/django-appointment/commit/fb07472985039f0e3b55a51a91e1e02695b60ea5): the mock was renamed (`send_email` became
  `send_confirmation`) and the staff ID was replaced with a boolean. The likely trigger was the `email` identifier,
  but that is an inference, not confirmed.
- **Human-directed corrections:** none.
- The Review and CodeQL results at the final head are recorded in the PR description.

## Unavailable evidence

- The `test-output` artifact and the raw job-log ZIP could not be fetched from the VM, because the storage host is not
  allowlisted and no extra storage hosts were requested. Job logs fetched through the GitHub integration were used
  instead.
- No production data, deployment or real email was involved, and no time or cost savings were measured.

## Proposed follow-ups (not filed)

1. Extend the confirm-time check to cover days off, other bookings and working hours. Reproduced risks 1–2; working
   hours is suspected.
2. Validate availability at reschedule **submit**, and decide whether rejected or blocked pending rows should count
   toward the reschedule limit. Reproduced risks 3 and 5.
3. Design a concurrency guard for the check-then-write window and verify it with a row-locking database test.

## Proposed Skill improvements (for human review; Skill left unchanged)

- Note that rendered pages echo the request path (language switcher), so "token not in body" assertions need care.
  Never let an assertion message print a token.
- Probe `print`s can trip CodeQL's clear-text logging rule through identifier names such as `email`. Keep probe
  output to neutral status flags.
