#!/usr/bin/env bash

set -euo pipefail

# Usage in Azure DevOps:
# - Checkout repo under test before running this script.
# - If this script is stored in a shared repository resource, checkout that resource too
#   so ShellScript@2 can execute file from workspace.
# - Run this step only for PullRequest builds when non-PR runs already use full pipeline flow.
# - Keep downstream stage conditions shaped so non-PR runs bypass PR output checks.
# - Script always includes `sbox` in `prTargetEnvs` and sets `prRunAllEnvs=true` for
#   `components/**` changes, so downstream conditions do not need separate `sbox` logic.
# - Give step stable name `detect_pr_envs` when downstream conditions reference outputs.
#
# Example:
#   - checkout: self
#   - ${{ if eq(variables['Build.Reason'], 'PullRequest') }}:
#       - checkout: cnp-azuredevops-libraries
#       - task: ShellScript@2
#         name: detect_pr_envs
#         inputs:
#           scriptPath: '$(Build.SourcesDirectory)/cnp-azuredevops-libraries/scripts/detect-pr-envs.sh'
#
# Downstream stage condition example:
#   and(
#     succeeded(),
#     or(
#       ne(variables['Build.Reason'], 'PullRequest'),
#       eq(dependencies.PreCheck.outputs['PreChecks.detect_pr_envs.prRunAllEnvs'], 'true'),
#       contains(dependencies.PreCheck.outputs['PreChecks.detect_pr_envs.prTargetEnvs'], ',${{ component.env }},')
#     )
#   )
#
# Generic assumptions for reuse:
# - env tfvars are stored as environments/<component>/<env>.tfvars
# - pipeline stage env names match <env> file basenames
# - script runs in Azure DevOps with git checkout available

pr_target_envs=",sbox,"
pr_run_all_envs=false

# Non-PR runs do not need env detection. Keep default output stable and exit fast.
if [[ "${BUILD_REASON:-}" != "PullRequest" ]]; then
  echo "PR detector skipped: BUILD_REASON=${BUILD_REASON:-unknown}"
  echo "PR target environments: ${pr_target_envs}"
  echo "##vso[task.setvariable variable=prTargetEnvs;isOutput=true]${pr_target_envs}"
  echo "##vso[task.setvariable variable=prRunAllEnvs;isOutput=true]${pr_run_all_envs}"
  exit 0
fi

repo_name="${BUILD_REPOSITORY_NAME##*/}"
repo_dir=""

candidates=(
  "${BUILD_REPOSITORY_LOCALPATH:-}"
  "${BUILD_SOURCESDIRECTORY:-}/${repo_name}"
  "${PIPELINE_WORKSPACE:-}/s/${repo_name}"
)

# Probe known checkout locations and use first valid git worktree.
for candidate in "${candidates[@]}"; do
  [[ -z "${candidate}" ]] && continue
  if git -C "${candidate}" rev-parse --show-toplevel >/dev/null 2>&1; then
    repo_dir="${candidate}"
    break
  fi
done

if [[ -z "${repo_dir}" ]]; then
  # Fail fast for PRs to avoid silently running wrong stage scope.
  echo "##vso[task.logissue type=error]No git checkout available in detected paths; failing PR detection"
  exit 1
fi

echo "Detecting PR environments from ${repo_dir}"

target_branch="${SYSTEM_PULLREQUEST_TARGETBRANCH:-refs/heads/main}"
target_short="${target_branch#refs/heads/}"
target_ref=""

# Build target-branch candidates in priority order:
# 1) Explicit PR target branch from Azure DevOps
# 2) Repo remote HEAD branch (origin/HEAD)
# 3) Common defaults (main, master)
candidate_branches=("${target_short}")

origin_head_short=""
if origin_head_ref=$(git -C "${repo_dir}" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null); then
  origin_head_short="${origin_head_ref#origin/}"
fi
if [[ -n "${origin_head_short}" ]]; then
  candidate_branches+=("${origin_head_short}")
fi
candidate_branches+=("main" "master")

# Resolve a usable target ref from local refs first, then fetch when needed.
for branch_name in "${candidate_branches[@]}"; do
  [[ -z "${branch_name}" ]] && continue

  if git -C "${repo_dir}" rev-parse --verify "${branch_name}" >/dev/null 2>&1; then
    target_ref="${branch_name}"
    break
  fi

  if git -C "${repo_dir}" rev-parse --verify "origin/${branch_name}" >/dev/null 2>&1; then
    target_ref="origin/${branch_name}"
    break
  fi

  if git -C "${repo_dir}" fetch --no-tags origin "${branch_name}:${branch_name}" --depth=1 >/dev/null 2>&1; then
    echo "Fetched target branch ${branch_name}"
    target_ref="${branch_name}"
    break
  fi
done

# If branch refs are unavailable (for example auth/depth limitations), use PR merge base
# from the checked out commit when available.
if [[ -z "${target_ref}" ]]; then
  if git -C "${repo_dir}" rev-parse --verify HEAD^1 >/dev/null 2>&1; then
    target_ref="HEAD^1"
    echo "Using HEAD^1 as target ref from PR merge commit"
  else
    echo "##vso[task.logissue type=error]Could not resolve PR target branch (${target_short}/main/master) and HEAD^1 is unavailable"
    exit 1
  fi
fi

echo "Using target ref ${target_ref}"

# Prefer three-dot diff for PR semantics. Fallback to two-dot when merge base is unavailable.
diff_ref="${target_ref}...HEAD"
if ! git -C "${repo_dir}" merge-base "${target_ref}" HEAD >/dev/null 2>&1; then
  echo "Three-dot diff unavailable here; using two-dot diff instead (${target_ref}..HEAD)"
  diff_ref="${target_ref}..HEAD"
fi

# Parse tfvars path convention and append unique env names in-place.
changed_files=()
mapfile -t changed_files < <(git -C "${repo_dir}" diff --name-only "${diff_ref}")

force_all_envs=false

for changed_file in "${changed_files[@]}"; do
  # Any file under components/ is treated as cross-environment impact.
  if [[ "${changed_file}" =~ ^components/.+ ]]; then
    force_all_envs=true
    break
  fi
done

if [[ "${force_all_envs}" == true ]]; then
  # components/** changes are treated as cross-environment impact.
  # Signal pipeline to run normal full PR stage flow without env diff filtering.
  echo "components/** change detected; disabling PR env diff filter"
  pr_run_all_envs=true
else
  while IFS= read -r changed_file; do
    if [[ "${changed_file}" =~ ^environments/[^/]+/([A-Za-z0-9_-]+)\.tfvars$ ]]; then
      env_name="${BASH_REMATCH[1]}"
      if [[ "${pr_target_envs}" != *",${env_name},"* ]]; then
        pr_target_envs+="${env_name},"
      fi
    fi
  done < <(printf '%s\n' "${changed_files[@]}")
fi

echo "PR target environments: ${pr_target_envs}"
echo "##vso[task.setvariable variable=prTargetEnvs;isOutput=true]${pr_target_envs}"
echo "PR run all environments: ${pr_run_all_envs}"
echo "##vso[task.setvariable variable=prRunAllEnvs;isOutput=true]${pr_run_all_envs}"