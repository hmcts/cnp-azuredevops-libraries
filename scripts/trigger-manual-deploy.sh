#!/usr/bin/env bash
echo "Starting Auto Manual Start workflows ..."

github_token="$1"
# three parameters are required to trigger the workflow: work area (sds, cft),
# environment(sandbox, aat/staging, demo, ithc, ptl, etc), and cluster (e.g. 00, 01, All)
project="$2"
environment="$3"
cluster="$4" # e.g. 00, 01, All

# set project to upper case
project_upper=$(echo "$project" | tr '[:lower:]' '[:upper:]')

# environment list: sbox, ptlsbox, ithc, ptl, stg, demo, test, dev

# define corresponding subscription IDs for each environment
SBOX_SUBIDs_MAP=(["DTS-SHAREDSERVICES-SBOX"]="a8140a9e-f1b0-481f-a4de-09e2ee23f7ab"
  ["DCD-CFTAPPS-SBOX"]="b72ab7b7-723f-4b18-b6f6-03b0f2c6a1bb")

ITHC_SUBIDs_MAP=(["DTS-SHAREDSERVICES-ITHC"]="ba71a911-e0d6-4776-a1a6-079af1df7139"
  ["DCD-CFTAPPS-ITHC"]="62864d44-5da9-4ae9-89e7-0cf33942fa09")

# check project needs to be either sds, cft, or All
if [[ $project != "ss" && $project != "cft" && $project != "All" ]]; then
  echo "[error] work_area must be sds, cft or All"
  exit 1
fi

## Check if requested clusters under a work area are running or not
# sds-sbox subscription ID: a8140a9e-f1b0-481f-a4de-09e2ee23f7ab
az account set -n DTS-SHAREDSERVICES-SBOX
cluster_data=$(az aks show -n ss-sbox-00-aks -g ss-sbox-00-rg -o json)
cluster_status=$(jq -r '.powerState.code' <<< "$cluster_data")
echo "ss-sbox-00-aks status $cluster_status."
# check if cluster is running or not
#if [[ $cluster_status != "Running" ]]; then
  echo "[info] Triggering auto manual start workflow for $project in $environment..."
  # Project: SDS or CFT; SELECTED_ENV: sbox, test/perftest, ptlsbox, ithc, ptl, aat/staging, demo, test, preview/dev;
  # AKS-INSTANCES: 00, 01, All
  curl -L \
         -X POST \
         -H "Accept: application/vnd.github+json" \
         -H "Authorization: Bearer $github_token" \
         -H "X-GitHub-Api-Version: 2022-11-28" \
         https://api.github.com/repos/hmcts/auto-shutdown/actions/workflows/manual-start.yaml/dispatches \
         -d "{ \"ref\": \"master\",
                \"inputs\": {
                  \"PROJECT\": \"$project_upper\",
                  \"SELECTED_ENV\": \"$environment\",
                  \"AKS-INSTANCES\": \"$cluster\"
                }
              }"
#else
#  echo "Cluster ss-sbox-00-aks is already running."
#fi