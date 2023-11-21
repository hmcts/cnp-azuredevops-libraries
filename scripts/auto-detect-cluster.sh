#!/usr/bin/env bash

set -euo pipefail

resourceGroupName=
aksClusterName=
environmentName=

usage(){
>&2 cat << EOF
------------------------------------------------
Script to check if AKS cluster is active state
------------------------------------------------
Usage: $0
    [ -r | --resourceGroupName ]
    [ -a | --aksClusterName ]
    [ -e | --environmentName ] 
    [ -h | --help ] 
EOF
exit 1
}

args=$(getopt -a -o r:a:e: --long resourceGroupName:,aksClusterName:,environmentName:,help -- "$@")
if [[ $? -gt 0 ]]; then
    usage
fi

# Debug commands, uncomment if you are having issues
# >&2 echo [$@] passed to script
# >&2 echo getopt creates [${args}]

eval set -- ${args}
while :
do
    case $1 in
        -h | --help)               usage                  ; shift   ;;
        -r | --resourceGroupName)  resourceGroupName=$2   ; shift 2 ;;
        -a | --aksClusterName)     aksClusterName=$2      ; shift 2 ;;
        -e | --environmentName)    environmentName=$2     ; shift 2 ;;
        # -- means the end of the arguments; drop this, and break out of the while loop
        --) shift; break ;;
        *) >&2 echo Unsupported option: $1
            usage ;;
    esac
done

if [ -z "$resourceGroupName" ] || [ -z "$aksClusterName" ] || [ -z "$environmentName" ]; then
        echo "------------------------" 
        echo 'Some values are missing, please supply AKS Resource Group, AKS Cluster name and AKS Environment name' >&2
        echo "------------------------"
        exit 1
fi

>&2 echo "resourceGroupName     : ${resourceGroupName}"
>&2 echo "aksClusterName        : ${aksClusterName} "
>&2 echo "environmentName       : ${environmentName}"

check_pod_in_cluster() {
    printf "\n\nTrying cluster $aksClusterName in $resourceGroupName\n"
    az aks get-credentials \
        --resource-group "$resourceGroupName" \
        --name "$aksClusterName" --admin
    local pod_exists=true
    pod_exists=$(kubectl get pods --context "$aksClusterName-admin" -n admin -o jsonpath='{range .items[*]}{@.metadata.name}{"\t"}{@.spec.containers[0].args}{"\n"}{end}' | grep "external-dns-private" | grep -- "--txt-owner-id=$environmentName-active")
    if [ -n "$pod_exists" ]; then
        setAksResourceGroup="$resourceGroupName"
        setAksCluster="$aksClusterName"
        return 0
    else
        return 1
    fi
}

if check_pod_in_cluster; then
    echo "Pod with the specified argument found in cluster - $setAksCluster."
    echo "----------- Setting Pipeline Variables -----------------"
    echo "##vso[task.setvariable variable=aksResourceGroup;isreadonly=true]$setAksResourceGroup"
    echo "##vso[task.setvariable variable=aksCluster;isreadonly=true]$setAksCluster"
else
    echo "Pod with the specified argument NOT found in cluster - $aksClusterName."
fi