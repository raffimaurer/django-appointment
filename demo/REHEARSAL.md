# Incident rehearsal: setup and automation handoff

Synthetic data, real upstream defect (see `demo/README.md`). No real customer
or NHS affiliation. Local/demo use only; never deploy `appointments.demo_settings`.

## Branches

| Branch | Purpose |
| --- | --- |
| `demo/ready` | Base for rehearsals: incident starting point plus Skill, CI and issue form. |
| `demo/incident` | Backup of the original incident starting point. Do not modify. |
| Existing repair PR branch | Backup of an earlier repair. Do not use as a base or copy from it. |

## Exact local setup

```bash
git clone https://github.com/raffimaurer/django-appointment.git
cd django-appointment
git checkout demo/ready
python3.12 -m venv .venv            # or: uv venv --python 3.12 .venv
.venv/bin/python -m pip install -r demo-requirements.lock
export DJANGO_SETTINGS_MODULE=appointments.demo_settings
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations appointment   # output is git-ignored
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py test appointment.tests.test_incident_reschedule -v 2
.venv/bin/python manage.py test appointment
```

## Expected baseline results (demo/ready, unrepaired)

- Incident tests: `Ran 7 tests`, `FAILED (failures=3)`.
- Full suite: `Ran 576 tests`, `FAILED (failures=3, skipped=3)`.
- The three expected failures, locally and in hosted CI:
  - `test_confirmation_rejects_new_block_without_mutation`
  - `test_partial_overlap_rejected`
  - `test_real_submit_then_block_then_confirm`

Hosted `demo-verify` (`.github/workflows/demo-verify.yml`) therefore fails
(red) on the baseline by design. Any other failure, or a different count, is
unexpected and must be investigated. Do not greenwash these failures. A
repaired PR should pass all 576 tests plus any additional meaningful tests it adds.
`demo-verify` runs on pull requests targeting `demo/ready` and via manual
dispatch, and uploads the full test output as the `test-output` artifact.

## Issue intake

1. Open an issue with the **Synthetic demo incident** form
   (`.github/ISSUE_TEMPLATE/demo-incident.yml`). It applies `demo-rehearsal` only.
2. A human triages it and then applies `devin-investigate`
   ("human-triaged synthetic incident approved for bounded Devin investigation").

## Automation handoff requirements

Any agent or automation working the incident must:

1. Use `demo/ready` in `raffimaurer/django-appointment` as the base. Record its SHA.
2. Explicitly read and follow
   `.agents/skills/scheduling-incident-investigation/SKILL.md` from the checked-out branch.
3. Reproduce the baseline (7 / 3 failures; 576 / 3 failures / 3 skips) before editing.
4. Keep all seven acceptance tests in
   `appointment/tests/test_incident_reschedule.py` unchanged.
5. Work on a separate fix branch and open a **draft** PR to `demo/ready` in this
   fork (never upstream), linking the originating issue.
6. Return actual before/after commands and counts, and the `demo-verify` result.
7. Include a bounded related-risk audit, separating reproduced from suspected risks.
8. Never log confirmation/reset tokens or full token URLs.
9. Never merge, deploy, or change repository settings or branch protection.

No automation is configured yet; this section defines the contract for one.

## Task template

```text
Investigate synthetic incident <ISSUE_URL> in raffimaurer/django-appointment.
Base: demo/ready (record the exact SHA).
First read and follow .agents/skills/scheduling-incident-investigation/SKILL.md
from the checked-out branch, and demo/REHEARSAL.md.
Reproduce the baseline before editing (expect 7 tests / 3 failures and
576 tests / 3 failures / 3 skips with appointments.demo_settings, Python 3.12,
demo-requirements.lock). Keep the seven acceptance tests unchanged.
Fix on a new branch; open a draft PR to demo/ready in this fork that links
<ISSUE_URL>. Report base SHA, commands, before/after counts, demo-verify run,
and a bounded related-risk audit (reproduced vs suspected). Do not merge or deploy.
```
