#!/usr/bin/env bash
#
# Reproducibly (re)apply `main` branch protection + repo merge settings.
#
# This is the version-controlled source of truth for the GitHub-side trust
# boundary described in AGENTS.md / docs/agents/LOOP.md / CONTRIBUTING.md.
# Branch protection is GitHub *state*, not a repo file — if it is ever
# cleared, or the repo is migrated/forked, run this to restore it exactly.
#
# Idempotent: safe to re-run. Requires `gh` authenticated with admin on the
# repo. Derives the repo from the current `gh`/git context (not hardcoded).
#
# The required status-check contexts below MUST equal the CI job `name:`
# values in .github/workflows/ci.yml — keep them in lockstep, or PRs will
# wait forever on a context that never reports.
#
set -euo pipefail

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Applying branch protection to: ${REPO} (branch: main)"

gh api -X PUT "repos/${REPO}/branches/main/protection" --input - >/dev/null <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["make check (pytest + ruff + mypy)", "no committed secrets"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

gh api -X PATCH "repos/${REPO}" \
  -F allow_auto_merge=true \
  -F delete_branch_on_merge=true \
  -F allow_merge_commit=false \
  -F allow_squash_merge=true >/dev/null

echo "Done. Effective protection:"
gh api "repos/${REPO}/branches/main/protection" --jq '{
  required_checks: .required_status_checks.contexts,
  strict: .required_status_checks.strict,
  enforce_admins: .enforce_admins.enabled,
  pr_approvals_required: .required_pull_request_reviews.required_approving_review_count,
  require_code_owner: .required_pull_request_reviews.require_code_owner_reviews,
  linear_history: .required_linear_history.enabled,
  force_pushes: .allow_force_pushes.enabled,
  deletions: .allow_deletions.enabled
}'
