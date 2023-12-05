#!/usr/bin/env bash
echo "Starting Auto Manual Start workflows ..."

github_token="$1"
# three parameters are required to trigger the workflow: work area (sds, cft),
# environment(sandbox, aat/staging, demo, ithc, ptl, etc), and cluster (e.g. 00, 01, All)
project="$2"
work_area="$2"
environment="$3"
cluster="$4" # e.g. 00, 01, All

# github token is $1 and work_area is $2 and environment is $3
function trigger_workflow() {
  # Project: SDS or CFT; SELECTED_ENV: sbox, test/perftest, ptlsbox, ithc, ptl, aat/staging, demo, test, preview/dev;
  # AKS-INSTANCES: 00, 01, All
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
function check_health_and_start_environment() {

TEST_URL_CFT="https://plum.sandbox.platform.hmcts.net/health"
TEST_URL_SDS="https://toffee.sandbox.platform.hmcts.net/health"

if [[ $environment == "ithc" ]]; then
  TEST_URL_CFT="https://plum.ithc.platform.hmcts.net/health"
else
  TEST_URL_SDS="https://toffee.ithc.platform.hmcts.net/health"
fi

MAX_ATTEMPTS=20
SLEEP_TIME=5
attempts=1
healthy=false
while (( attempts <= MAX_ATTEMPTS ))
do
  echo "Attempt #$attempts"
  if [[ $work_area == "CFT" ]]; then
  response=$(curl -sk -o /dev/null -w "%{http_code}" "$TEST_URL_CFT")
  else
  response=$(curl -sk -o /dev/null -w "%{http_code}" "$TEST_URL_SDS")
  fi
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
trigger_workflow "$github_token" "$work_area" "$environment"
fi
}

# check project needs to be either sds, cft, or All
#if [[ $project != "ss" && $project != "cft" && $project != "All" ]]; then
#  echo "[error] project must be sds, cft or All. received $project."
#  exit 1
#fi

# check work_area needs to be set to sds when project is ss
#if [[ $project == "ss" ]]; then
#  work_area="sds"
#fi

# set work_area to upper case i.e. SDS, CFT
work_area=$(echo "$work_area" | tr '[:lower:]' '[:upper:]')

# environment list: sbox, ptlsbox, ithc, ptl, stg, demo, test, dev

# define corresponding subscription IDs for each environment
SBOX_SUBIDs_MAP=(["DTS-SHAREDSERVICES-SBOX"]="a8140a9e-f1b0-481f-a4de-09e2ee23f7ab"
  ["DCD-CFTAPPS-SBOX"]="b72ab7b7-723f-4b18-b6f6-03b0f2c6a1bb")

ITHC_SUBIDs_MAP=(["DTS-SHAREDSERVICES-ITHC"]="ba71a911-e0d6-4776-a1a6-079af1df7139"
  ["DCD-CFTAPPS-ITHC"]="62864d44-5da9-4ae9-89e7-0cf33942fa09")

## Check if requested clusters under a work area are running or not
# sds-sbox subscription ID: a8140a9e-f1b0-481f-a4de-09e2ee23f7ab

if [[ $work_area == "SDS" ]]; then
  if [[ $environment == "sbox" ]]; then
    az account set -n DTS-SHAREDSERVICES-SBOX
    else
    az account set -n DTS-SHAREDSERVICES-ITHC
  fi
elif [[ $environment == "sbox" ]]; then
    az account set -n DCD-CFTAPPS-SBOX
    else
    az account set -n DCD-CFTAPPS-ITHC
fi

if [[ $environment == "All" ]]; then
  echo "Triggering auto manual start workflow for all projects in $environment for cluster $cluster"
  trigger_workflow "$github_token" "SDS" "$environment"
  trigger_workflow "$github_token" "CFT" "$environment"
  exit 0
fi

check_health_and_start_environment "$github_token" "$work_area" "$environment"
