#!/usr/bin/env bash
echo "Starting Auto Manual Start workflows ..."
github_token="$1"
project="$2"
environment="$3"
on_demand_environments=("sbox")
MODE="start"

# Only run for currently approved on demand environments
if [[ ! " ${on_demand_environments[@]} " =~ " ${environment}" ]]; then
    # Add your script logic here
    echo "Not checking environment as not included in on demand list"
    exit 0
fi

project=$(echo "$project" | tr '[:lower:]' '[:upper:]')
if [[ $project == "SS" ]]; then
  project="SDS"
fi

function trigger_workflow() {
  curl -L \
         -X POST \
         -H "Accept: application/vnd.github+json" \
         -H "Authorization: Bearer $1" \
         -H "X-GitHub-Api-Version: 2022-11-28" \
         https://api.github.com/repos/hmcts/auto-shutdown/actions/workflows/manual-start-stop.yaml/dispatches \
         -d "{ \"ref\": \"master\",
                \"inputs\": {
                  \"SELECTED_MODE\": \"$2\",
                  \"SELECTED_AREA\": \"$3\",
                  \"SELECTED_ENV\": \"$4\"
                }
              }"
}

# Function to check if a given endpoint for an environment is up
function check_environment_health() {
  project="$1"
  environment="$2"
  project_url="plum" && [[ "${project}" == "SDS" ]] && project_url="toffee"
  env="sandbox" && [[ "${environment}" != "sbox" ]] && env=$environment
  TEST_URL="https://${project_url}.${env}.platform.hmcts.net/health"

  MAX_ATTEMPTS=5
  SLEEP_TIME=3
  attempts=1

  while (( attempts <= MAX_ATTEMPTS ))
  do
    echo "Attempt #$attempts"
    response=$(curl -sk -o /dev/null -w "%{http_code}" "$TEST_URL")
    ((attempts++))
    if (( response >= 200 && response <= 399 )); then
      return
    else
      echo "Returned HTTP $response, retrying..."
      sleep $SLEEP_TIME
    fi
  done
  false
}

# Function that will trigger workflow if environment is not up, to start it
function start_unhealthy_environments() {
  github_token="$1"
  project="$2"
  environment="$3"

  if check_environment_health $project $environment; then
    echo "$project in $environment is healthy, returned HTTP $response. No need to trigger auto manual start workflow."
  else
    echo "[info] $project in $environment not healthy, triggering auto manual start workflow for $project in $environment"
    trigger_workflow "$github_token" "$MODE" "$project" "$environment"
    echo "[info] Manual start workflow for $project in $environment triggered.. waiting 5 minutes for environment to start"
    # Wait 5 minutes for environment to start
    sleep 300
    MAX_ATTEMPTS=5
    attempts=1
    healthy=false

    while (( attempts <= MAX_ATTEMPTS ))
    do
      if check_environment_health $project $environment; then
        echo "$project in $environment healthy, continue with build"
        healthy=true
        break
      else  
        echo "$project in $environment remains unhealthy, trying again.."
        ((attempts++))
        sleep 60
      fi
    done
    if ! $healthy; then
      echo "[error] There was a problem starting the environment, please reach out in #platops-help"
      exit 1
    fi
  fi
}

if [[ $project == "PANORAMA" ]]; then
  echo "Triggering auto manual start workflow for all projects in $environment"
  start_unhealthy_environments "$github_token" "SDS" "$environment"
  start_unhealthy_environments "$github_token" "CFT" "$environment"
  exit 0
fi

start_unhealthy_environments "$github_token" "$project" "$environment"
