# INC-2: stale reschedule confirmation accepts a blocked hour

> Synthetic smoke rehearsal. All data is synthetic. Nothing was deployed and there was no production recovery.
> No customer or organisational affiliation is claimed.

| | |
|---|---|
| Issue | [raffimaurer/django-appointment#2](https://github.com/raffimaurer/django-appointment/issues/2) |
| Pull request | [#6 (draft, unmerged)](https://github.com/raffimaurer/django-appointment/pull/6), base `demo/ready` |
| Base commit | [`757f2517de2d1728f211f8890939d8800fd39051`](https://github.com/raffimaurer/django-appointment/commit/757f2517de2d1728f211f8890939d8800fd39051) |
| Fix commit | [`2efced579aa185e70119bf49aa41d0adfef6a866`](https://github.com/raffimaurer/django-appointment/commit/2efced579aa185e70119bf49aa41d0adfef6a866) |
| Hosted CI (fix commit) | [demo-verify run 41533580188](https://github.com/raffimaurer/django-appointment/actions/runs/41533580188) (success), [artifact `test-output`](https://github.com/raffimaurer/django-appointment/actions/runs/41533580188/artifacts/13182313919) |
| Procedure | `.agents/skills/scheduling-incident-investigation/SKILL.md` as it exists at the base commit. The Skill was not changed. |

## Symptom and impact (synthetic)
A reschedule confirmation link that had not yet expired (5-minute window) moved an appointment into an hour that
the practitioner had blocked with an `Unavailability` *after* submitting the reschedule request. A fresh availability lookup
already hid that hour correctly. The illustrative impact is a conflicting booking that needs manual reconciliation.
That impact is part of the rehearsal scenario and was not observed in production.

## Reproduction (Skill §1-§2)
Environment: Python 3.12.16 (`.venv`), packages verified against `demo-requirements.lock` (0 mismatches),
`DJANGO_SETTINGS_MODULE=appointments.demo_settings`, SQLite and the locmem mail backend.
`manage.py check`, `makemigrations appointment` and `migrate` ran first. The generated migrations were not committed.

```
python manage.py test appointment.tests.test_incident_reschedule   # Ran 7 tests  FAILED (failures=3)
python manage.py test appointment                                  # Ran 576 tests FAILED (failures=3, skipped=3)
```
The three failures (`test_confirmation_rejects_new_block_without_mutation`, `test_partial_overlap_rejected`,
`test_real_submit_then_block_then_confirm`) match the reported symptom. These counts are identical to the issue's acceptance criteria.

## Root cause (Skill §3)
- **Offer:** `get_available_slots_for_staff` excludes unavailabilities, days off, working hours, appointments and pending reschedules.
- **Hold:** `reschedule_appointment_submit` stores an `AppointmentRescheduleHistory` (`pending`) and emails a confirmation link.
- **Commit:** `confirm_reschedule` checked only `reschedule_status == 'pending'` and `still_valid()` (expiry). After that it copied the
  pending date/time/staff onto the `AppointmentRequest`, marked the history `confirmed` and called
  `notify_admin_about_reschedule`. It never re-checked availability that could have changed since the offer.

## Fix (Skill §4-§5)
- New `has_overlapping_unavailability(date, start_time, end_time, staff_member)` in `appointment/utils/db_helpers.py`.
  It uses half-open `[start, end)` semantics (`start_time__lt=end`, `end_time__gt=start`) and is scoped to the same staff member and date.
  The existing `get_unavailabilities_for_date_and_time` was deliberately not reused because its `lte/gte` filter treats
  touching boundaries as overlaps.
- `confirm_reschedule` calls it after the expiry/status check and **before** any write or notification. On conflict it
  renders the existing error page with HTTP **409** and a user-safe message. It does not write to the `AppointmentRequest` or the history row,
  does not call `notify_admin_about_reschedule`, and sends no email. The pending request stays pending, so the
  link works again if the block is removed before expiry.

### Prevention principle
**Revalidate mutable availability at confirmation, before changing data or sending notifications.** What was true
when a slot was offered can change while the request is held. The commit step is the last point where a conflict can
be caught cheaply and without side effects, so it must check current state, not trust the offer. This change applies the
principle to `Unavailability` only. The other mutable inputs are listed below as reproduced but not yet fixed.

## Tests (Skill §7)
| Run | Incident acceptance (7, unchanged) | Full suite |
|---|---|---|
| Before, local, base `757f251` | Ran 7, FAILED (failures=3) | Ran 576, FAILED (failures=3, skipped=3) |
| After, local, `2efced5` | Ran 7, OK | Ran 583, OK (skipped=3) |
| After, hosted demo-verify, `2efced5` | 7 ok (from artifact) | Ran 583, OK (skipped=3) |

The 3 skips are the same before and after, all `'Django-Q is not available'`:
`DjangoQUnavailableTest.test_placeholder`, `ScheduleEmailReminderTest` (setUpClass) and `UpdateAppointmentReminderTest` (setUpClass).
The hosted artifact `test-output.txt` was downloaded and inspected. It contains `Ran 583 tests` / `OK (skipped=3)`, the same three skips,
no `FAIL:`/`ERROR:` lines, and all 7 acceptance tests plus all 7 new tests reported `ok`.

New regression tests are in `appointment/tests/test_reschedule_confirmation_revalidation.py` (+7):
- `test_rejection_preserves_all_fields_and_sends_no_email`: a block that encloses the requested slot gets a 409. Every concrete field
  of both the `AppointmentRequest` and the pending `AppointmentRescheduleHistory` is unchanged, and `mail.outbox` is empty.
  The acceptance tests compare only four request fields and the history status, so this covers the issue's
  "preserve every original appointment and pending-history field" requirement.
- `test_link_usable_again_once_block_removed`: a rejection does not consume the pending request.
- `test_block_ending_at_requested_start_allowed`: covers the other half-open boundary (the acceptance tests only cover a block
  that starts at the slot's end).
- `test_same_staff_block_on_other_date_allowed`: checks the date scoping (the acceptance tests only cover another staff member).
- `HasOverlappingUnavailabilityTests` (3): unit tests for the helper's interval semantics, scoping and a `None` staff member.

How these prevent recurrence: with the view guard reverted (helper kept), the 3 acceptance tests and 2 of the new tests
(`test_rejection_preserves_all_fields_and_sends_no_email`, `test_link_usable_again_once_block_removed`) fail.
The other new tests are guards against over-blocking. They pass both before and after the fix and would fail if a
future change rejected adjacent or out-of-scope blocks.

Lint: `flake8 --max-line-length 120` (system flake8 7.3.0; flake8 is not in the lockfile) reports nothing for the new test file.
It reports 9 warnings for `views.py` and `db_helpers.py` both before and after the change, so none were introduced.

## Review findings and handling
Devin Review on `2efced5` ([review](https://app.devin.ai/review/raffimaurer/django-appointment/pull/6)) found **0** bug, security,
code-quality or flag findings, and the Devin Review check passed. It added 2 *info* notes:
1. *Other availability changes remain unchecked* (days off, appointments, working hours, gap time). Agreed. This is out of scope and was
   reproduced (see below). It is escalated for human prioritisation as follow-up 1 and not fixed here.
2. *Conflict displays a 404 page* (the shared error template's title says "Page not found | 404" while the status is 409). Accurate and
   cosmetic. The message body explains the conflict. The existing invalid-link path reuses the same template. Fixing it means
   adding a new template, which is beyond this narrow fix, so it is escalated for human decision and not fixed.

Devin Review on the docs commit `0ae6f49` again found **0** bug, security or code-quality findings (check passed). It repeated the same 2 info notes and
added 1 *flag*: *incident report absent from site navigation (`mkdocs.yml`)*. This is escalated without a change. The report is an
internal record that the PR and the issue link to directly. Adding it to the published docs sidebar is a human documentation decision.
The docs workflow only targets `main` and mkdocs is not in strict mode, so nothing breaks
([PR comment](https://github.com/raffimaurer/django-appointment/pull/6#issuecomment-6589637014)).

Info and flag notes are not part of the triage set (`report_triage` rejected them as unknown IDs). They were answered in PR comments instead ([round 1](https://github.com/raffimaurer/django-appointment/pull/6#issuecomment-6589601460)).
**Auto-Fix:** the review notification said Auto-Fix was enabled, but it had no actionable findings. No automatic commits were
made and the branch contains only commits authored in this session. No corrections were needed in this round, human-directed or automatic.

## Remaining risks (Skill §9, 10-minute timebox)
**Reproduced defects** (with a throwaway local test that called `confirm_reschedule` after changing state; the test was not committed, and none of these are fixed here):
- A `DayOff` added after the request still lets confirmation succeed (302).
- An overlapping existing appointment for the same staff member and time, created after the request, still lets confirmation succeed (302).
- Working hours changed so the slot falls outside them still let confirmation succeed (302).

**Inspection concerns** (from reading the code only; not reproduced):
- `reschedule_appointment_submit` does not validate the requested slot against availability on the server (it relies on the offer UI).
- `confirm_reschedule` does a read, then a check, then writes, outside a transaction, and does not lock or conditionally update the history row. Double confirmation or
  check-then-write races are **unverified**: SQLite serialises writes, so the test runs cannot show them.
- Staff gap time (`get_staff_member_slot_gap_time`) is not re-checked at confirmation.
- The 409 response reuses the 404-titled template (review info note 2).

## Proposed prevention follow-ups (prioritised; not created)
1. Use one shared "is this slot still bookable" check (unavailability, day off, working hours, other appointments, gap time) for
   both the offer and confirmation, and cover each reproduced defect above with a test.
2. Make confirmation atomic and idempotent, for example a transaction plus a conditional `pending -> confirmed` update, and verify it on a
   database with real concurrency (e.g. PostgreSQL).
3. Re-validate on the server at reschedule submit, and give conflicts a dedicated 409 template.

## Proposed Skill updates (for human review; the Skill is unchanged and this is not approved policy)
- §3/§9: suggest a short, uncommitted probe test per sibling availability input (day off, working hours, appointments, gap time),
  so that "reproduced" vs "suspected" is decided by evidence quickly.
- §4: warn that existing query helpers may use inclusive bounds (`get_unavailabilities_for_date_and_time` uses `lte/gte`), so check
  their semantics before reusing them for commit-time conflicts.
- §10: tell the investigator to download and inspect the hosted CI artifact, not just the check status, and note that artifact
  downloads may need the GitHub artifact blob host on a restricted network allowlist.

## Limitations
- Local runs used SQLite and in-memory mail. Hosted CI is the `demo-verify` workflow only. No browser/UI testing was done.
  The change is server-side and is covered by Django test-client tests.
- No concurrency claims are made (see the inspection concerns).
- This report records CI and review results for the commits listed. A file cannot record CI for the commit that adds it, so the
  results for the latest documentation-only commit are reported in the PR description and the final issue reply.

## Final verification status
| Commit | demo-verify (hosted) | Artifact | CodeQL | Devin Review |
|---|---|---|---|---|
| [`2efced5`](https://github.com/raffimaurer/django-appointment/commit/2efced579aa185e70119bf49aa41d0adfef6a866) fix | [run 41533580188](https://github.com/raffimaurer/django-appointment/actions/runs/41533580188): success, Ran 583, OK (skipped=3) | [13182313919](https://github.com/raffimaurer/django-appointment/actions/runs/41533580188/artifacts/13182313919) downloaded and inspected | success | passed: 0 bug/security, 2 info (escalated) |
| [`0ae6f49`](https://github.com/raffimaurer/django-appointment/commit/0ae6f4935d946ccc692900d54f4669b90c2f8859) docs | [run 41533895636](https://github.com/raffimaurer/django-appointment/actions/runs/41533895636): success, Ran 583, OK (skipped=3) | [13183276133](https://github.com/raffimaurer/django-appointment/actions/runs/41533895636/artifacts/13183276133): downloaded and inspected after the blob host was approved (sha256 `47445697…`): Ran 583, OK (skipped=3), the same 3 Django-Q skips, 14/14 incident tests ok, no FAIL or ERROR lines | success | passed: 0 bug/security, 2 info + 1 flag (escalated) |
| [`527161e`](https://github.com/raffimaurer/django-appointment/commit/527161ea94e2d3afba5e046bab6cc58eff9ba810) docs | [run 41534222058](https://github.com/raffimaurer/django-appointment/actions/runs/41534222058): success | [13183062980](https://github.com/raffimaurer/django-appointment/actions/runs/41534222058/artifacts/13183062980): metadata only (sha256 `877846f6…`). GitHub served the zip from a third blob host that this session's network allowlist does not include | see PR | passed: 0 findings |

The CI and review results for the commit that adds this table are in the PR description and the final issue reply.
The PR stays **draft and unmerged**. Nothing was deployed.
