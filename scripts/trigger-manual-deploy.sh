#!/usr/bin/env bash
echo "Starting Auto Manual Start workflows ..."

github_token="$1"

project="$2"

project=$(echo "$project" | tr '[:lower:]' '[:upper:]')
if [[ $project == "SS" ]]; then
  project="SDS"
fi

# environment list: sbox, ptlsbox, ithc, ptl, stg, demo, test, dev
environment="$3"

# three parameters are required to trigger the workflow: github token, work area (sds, cft),
# environment(sandbox, aat/staging, demo, ithc, ptl, etc). The cluster is set 00.

# github token is $1 and work_area is $2 and environment is $3
function trigger_workflow() {
  echo "Workflow params: $1 $2 $3"

  # Project: SDS or CFT or PANORAMA; SELECTED_ENV: sbox, test/perftest, ptlsbox, ithc, ptl, aat/staging, demo, test, preview/dev;
  curl -L \
         -X POST \
         -H "Accept: application/vnd.github+json" \
         -H "Authorization: Bearer $1" \
         -H "X-GitHub-Api-Version: 2022-11-28" \
         https://api.github.com/repos/hmcts/auto-shutdown/actions/workflows/manual-start.yaml/dispatches \
         -d "{ \"ref\": \"master\",
                \"inputs\": {
                  \"PROJECT\": \"$2\",
                  \"SELECTED_ENV\": \"$3\",
                  \"AKS-INSTANCES\": \"00\"
                }
              }"
}

# github token is $1 and work_area is $2 and environment is $3
function start_unhealthy_environments() {
project_url="plum" && [[ "${project}" == "SDS" ]] && project_url="toffee"
env="sandbox" && [[ "${environment}" != "sbox" ]] && env=$environment
TEST_URL="https://${project_url}.${env}.platform.hmcts.net/health"

MAX_ATTEMPTS=20
SLEEP_TIME=5
attempts=1
healthy=false

while (( attempts <= MAX_ATTEMPTS ))
do
  echo "Attempt #$attempts"
  response=$(curl -sk -w "%{http_code}" "$TEST_URL")
  ((attempts++))
  if (( response >= 200 && response <= 399 )); then
    healthy=true;
    break;
  else
    echo "Returned HTTP $response, retrying..."
    sleep $SLEEP_TIME
  fi
done

if [[ $healthy == true ]]; then
  echo "Service is healthy, returned HTTP $response. No need to trigger auto manual start workflow."
else
  echo "[info] Service not healthy, triggering auto manual start workflow for $project in $environment for cluster 00"
  trigger_workflow "$github_token" "$project" "$environment"
fi
}

# define corresponding subscription IDs for each environment
declare -A SBOX_SUBIDs_MAP=(["DTS-SHAREDSERVICES-SBOX"]="a8140a9e-f1b0-481f-a4de-09e2ee23f7ab"
  ["DCD-CFTAPPS-SBOX"]="b72ab7b7-723f-4b18-b6f6-03b0f2c6a1bb")

declare -A ITHC_SUBIDs_MAP=(["DTS-SHAREDSERVICES-ITHC"]="ba71a911-e0d6-4776-a1a6-079af1df7139"
  ["DCD-CFTAPPS-ITHC"]="62864d44-5da9-4ae9-89e7-0cf33942fa09")

echo "project is $project and environment is $environment"
if [[ $project == "SDS" ]]; then
  if [[ $environment == "sbox" ]]; then
    az account set -n "${SBOX_SUBIDs_MAP["DTS-SHAREDSERVICES-SBOX"]}"
    else
    az account set -n "${ITHC_SUBIDs_MAP["DTS-SHAREDSERVICES-ITHC"]}"
  fi
fi

if [[ $project == "CFT" ]]; then
  if [[ $environment == "sbox" ]]; then
    az account set -n "${SBOX_SUBIDs_MAP["DCD-CFTAPPS-SBOX"]}"
    else
    az account set -n "${ITHC_SUBIDs_MAP["DCD-CFTAPPS-ITHC"]}"
  fi
fi

if [[ $project == "PANORAMA" ]]; then
  echo "Triggering auto manual start workflow for all projects in $environment"
  start_unhealthy_environments "$github_token" "SDS" "$environment"
  start_unhealthy_environments "$github_token" "CFT" "$environment"
  exit 0
fi

start_unhealthy_environments "$github_token" "$project" "$environment"
