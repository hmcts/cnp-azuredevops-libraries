#!/usr/bin/env bash

set -euo pipefail

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

# Use local target ref when available. Fetch only when missing to reduce network cost.
if ! git -C "${repo_dir}" rev-parse --verify "${target_short}" >/dev/null 2>&1; then
  if git -C "${repo_dir}" fetch --no-tags origin "${target_short}:${target_short}" --depth=1 2>/dev/null; then
    echo "Fetched target branch ${target_short}"
  else
    echo "##vso[task.logissue type=error]Could not fetch target branch ${target_short}; failing PR detection"
    exit 1
  fi
fi

if ! git -C "${repo_dir}" rev-parse --verify "${target_short}" >/dev/null 2>&1; then
  echo "##vso[task.logissue type=error]Target branch ${target_short} is unavailable after fetch; failing PR detection"
  exit 1
fi

# Prefer three-dot diff for PR semantics. Fallback to two-dot when merge base is unavailable.
diff_ref="${target_short}...HEAD"
if ! git -C "${repo_dir}" merge-base "${target_short}" HEAD >/dev/null 2>&1; then
  echo "Three-dot diff unavailable here; using two-dot diff instead (${target_short}..HEAD)"
  diff_ref="${target_short}..HEAD"
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