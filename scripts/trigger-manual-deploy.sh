#!/usr/bin/env bash
echo "Starting Auto Manual Start workflows ..."
github_token="$1"
project="$2"
environment="$3"
cluster="$4"
on_demand_environments=("sbox")

# Only run for currently approved on demand environments
if [[ ! " ${on_demand_environments[@]} " =~ " ${environment}" ]]; then
    # Add your script logic here
    echo "Not checking environment as not included in on demand list"
    exit 1
fi

project=$(echo "$project" | tr '[:lower:]' '[:upper:]')
if [[ $project == "SS" ]]; then
  project="SDS"
fi

project="CFT"

function trigger_workflow() {
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
                  \"AKS-INSTANCES\": \"$4\"
                }
              }"
}

# github token is $1 and work_area is $2 and environment is $3
function start_unhealthy_environments() {
  github_token="$1"
  project="$2"
  environment="$3"
  cluster="$4"

  project_url="plum" && [[ "${project}" == "SDS" ]] && project_url="toffee"
  env="sandbox" && [[ "${environment}" != "sbox" ]] && env=$environment
  TEST_URL="https://${project_url}.${env}.platform.hmcts.net/health"

  MAX_ATTEMPTS=10
  SLEEP_TIME=5
  attempts=1
  healthy=false

  while (( attempts <= MAX_ATTEMPTS ))
  do
    echo "Attempt #$attempts"
    response=$(curl -sk -o /dev/null -w "%{http_code}" "$TEST_URL")
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
    echo "[info] Service not healthy, triggering auto manual start workflow for $project in $environment for cluster $cluster"
    trigger_workflow "$github_token" "$project" "$environment" "$cluster"
  fi
}

# define corresponding subscription IDs for each environment
declare -A subscription_id_map=(
  ["CFT-SBOX"]="b72ab7b7-723f-4b18-b6f6-03b0f2c6a1bb"
  ["CFT-ITHC"]="62864d44-5da9-4ae9-89e7-0cf33942fa09"
  ["SDS-SBOX"]="a8140a9e-f1b0-481f-a4de-09e2ee23f7ab"
  ["SDS-ITHC"]="ba71a911-e0d6-4776-a1a6-079af1df7139"
)

subscription_id="${subscription_id_map["${project}-${environment^^}"]}"

echo "The project is $project and the environment is $environment"
az account set -n "$subscription_id"

if [[ $project == "PANORAMA" ]]; then
  echo "Triggering auto manual start workflow for all projects in $environment"
  start_unhealthy_environments "$github_token" "SDS" "$environment" "$cluster"
  start_unhealthy_environments "$github_token" "CFT" "$environment" "$cluster"
  exit 0
fi

start_unhealthy_environments "$github_token" "$project" "$environment" "$cluster"