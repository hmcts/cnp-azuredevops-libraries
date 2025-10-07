#!/usr/bin/env bash

# Improve error handling to consider errors in piped commands
set -o pipefail

echo "Starting Auto Manual Start workflows ..."
# GitHub App authentication details needed to get an app installation token
# https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation#using-an-installation-access-token-to-authenticate-as-an-app-installation
github_app_priv_key=$1
github_app_id=$2
github_app_installation_id=$3
project="$4"
environment="$5"
on_demand_environments=("sbox")
MODE="start"
GITHUB_APP_INSTALLATION_ACCESS_TOKEN=""

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

b64enc() { 
  openssl base64 | tr -d '=' | tr '/+' '_-' | tr -d '\n';
}

function get_access_token() {
  now=$(date +%s)
  iat=$((${now} - 60)) # Issues 60 seconds in the past
  exp=$((${now} + 600)) # Expires 10 minutes in the future
  
  header_json='{
      "typ":"JWT",
      "alg":"RS256"
  }'
  # Header encode
  header=$( echo -n "${header_json}" | b64enc )
  payload_json="{
      \"iat\":${iat},
      \"exp\":${exp},
      \"iss\":\"${github_app_id}\"
  }"
  # Payload encode
  payload=$( echo -n "${payload_json}" | b64enc )
  # Signature
  header_payload="${header}"."${payload}"
  signature=$(
      openssl dgst -sha256 -sign <(echo -n "${github_app_priv_key}") \
      <(echo -n "${header_payload}") | b64enc
  )

  # Create JWT
  JWT="${header_payload}"."${signature}"

  # Get the installation access token - expires after 1 hour
  curl --request POST \
      --url https://api.github.com/app/installations/${github_app_installation_id}/access_tokens \
      --header "Accept: application/vnd.github+json" \
      --header "Authorization: Bearer ${JWT}" \
      --header "X-GitHub-Api-Version: 2022-11-28" \
      --silent | jq -r .token
}

function trigger_workflow() {
  # Trigger the workflow dispatch event using dedicated GitHub App with action: write permission on auto-shutdown repo
  # See: AKS Manual Start Workflow GitHub App in Platform Operations/HMCTS GitHub Apps
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
  # Only generate the app installation access token if it doesn't already exist
  if [[ -z "$GITHUB_APP_INSTALLATION_ACCESS_TOKEN" ]]; then
    GITHUB_APP_INSTALLATION_ACCESS_TOKEN=$(generate_access_token)
  fi

  project="$2"
  environment="$3"

  if check_environment_health $project $environment; then
    echo "$project in $environment is healthy, returned HTTP $response. No need to trigger auto manual start workflow."
  else
    echo "[info] $project in $environment not healthy, triggering auto manual start workflow for $project in $environment"
    trigger_workflow "${GITHUB_APP_INSTALLATION_ACCESS_TOKEN}" "$MODE" "$project" "$environment"
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
  start_unhealthy_environments "SDS" "$environment"
  start_unhealthy_environments "CFT" "$environment"
  exit 0
fi

start_unhealthy_environments "$project" "$environment"
