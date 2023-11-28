#!/usr/bin/env bash
echo "Starting Auto Manual Start workflows ..."

github_token="$1"
# three parameters are required to trigger the workflow: work area (sds, cft),
# environment(sandbox, aat/staging, demo, ithc, ptl, etc), and cluster (e.g. 00, 01, All)
project="$2"
work_area="$2"
environment="$3"
cluster="$4" # e.g. 00, 01, All

# check project needs to be either sds, cft, or All
if [[ $project != "ss" && $project != "cft" && $project != "All" ]]; then
  echo "[error] project must be sds, cft or All. received $project."
  exit 1
fi

# check work_area needs to be set to sds when project is ss
if [[ $project == "ss" ]]; then
  work_area="sds"
fi

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
az account set -n DTS-SHAREDSERVICES-SBOX

#Although we may ask for 'ALL' clusters to be started, we only need to include the ones that are not running in the request

if [[ $cluster == "00" ]] || [[ $cluster == "All" ]]; then
  echo "Checking ss-sbox-00-aks status..."
  cluster_data_00=$(az aks show -n ss-sbox-00-aks -g ss-sbox-00-rg -o json)
  cluster_status_00=$(jq -r '.powerState.code' <<< "$cluster_data_00")
  echo "ss-sbox-00-aks status $cluster_status_00."
    if [[ $cluster_status_00 != "Running" ]]; then
      clustersToStart="00"
    fi
    elif [[ $cluster == "00" ]] && [[ $cluster_status_00 == "Running" ]]; then
    echo "Cluster 00 is already running. Exiting..."
      exit;
fi

if [[ $cluster == "01" ]] || [[ $cluster == "All" ]]; then
  echo "Checking ss-sbox-01-aks status..."
  cluster_data_01=$(az aks show -n ss-sbox-01-aks -g ss-sbox-01-rg -o json)
  cluster_status_01=$(jq -r '.powerState.code' <<< "$cluster_data_01")
  echo "ss-sbox-01-aks status $cluster_status_01."

    if [[ $cluster_status_01 == "Running" ]] && [[ $cluster_status_00 == "Running" ]]; then
      echo "Both clusters are already running. Exiting..."
      exit;
    fi
    if [[ $cluster == "ALL" && $cluster_status_01 != "Running" ]] && [[ $cluster_status_00 != "Running" ]]; then
      clustersToStart="ALL"
    fi
    elif [[ $cluster == "ALL" && $cluster_status_01 != "Running" ]] && [[ $cluster_status_00 == "Running" ]]; then
      clustersToStart="01"
    elif [[ $cluster == "ALL" && $cluster_status_01 == "Running" ]] && [[ $cluster_status_00 != "Running" ]]; then
      clustersToStart="00"

    if [[ $cluster_status_01 != "Running" ]]; then
      clustersToStart="01"
    fi
    elif [[ $cluster == "01" ]] && [[ $cluster_status_01 == "Running" ]]; then
    echo "Cluster 01 is already running. Exiting..."
      exit;
fi

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
                  \"PROJECT\": \"$work_area\",
                  \"SELECTED_ENV\": \"$environment\",
                  \"AKS-INSTANCES\": \"$clustersToStart\"
                }
              }"
#else
#  echo "Cluster ss-sbox-00-aks is already running."
#fi