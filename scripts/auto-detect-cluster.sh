#!/bin/bash

usage() {
    echo "------------------------"
    echo "Script to check which AKS cluster is active"
    echo "------------------------"
    echo "Usage: $0 -r <aksResourceGroupName> -k <aksClusterName> -e <aksEnvironmentName>"
    echo "------------------------"
    return 1
}
OPTIND=1

while getopts r:k:e: o; do
    case "$o" in
        r)
            aksResourceGroupName="$OPTARG"
            ;;
        k)
            aksClusterName="$OPTARG"
            ;;
        e)
            aksEnvironmentName="$OPTARG"
            ;;
        --)
            break
            ;;
        *)
            echo "Unrecognized option '${flag}'"
            usage
            exit
            ;;
    esac
done


if [ -z "$aksResourceGroupName" ] || [ -z "$aksClusterName" ] || [ -z "$aksEnvironmentName" ]; then
        echo "------------------------" 
        echo 'Some values are missing, please supply AKS Resource Group, AKS Cluster name and AKS Environment name' >&2
        echo "------------------------"
        exit 1
fi

echo "aksResourceGroupName: $aksResourceGroupName";
echo "aksClusterName: $aksClusterName";
echo "aksEnvironmentName: $aksEnvironmentName";

check_pod_in_cluster() {
    printf "\n\nTrying cluster $aksClusterName in $aksResourceGroupName\n"
    az aks get-credentials \
        --resource-group "$aksResourceGroupName" \
        --name "$aksClusterName" --admin
    local pod_exists
    pod_exists=$(kubectl get pods --context "$aksClusterName-admin" -n admin -o jsonpath='{range .items[*]}{@.metadata.name}{"\t"}{@.spec.containers[0].args}{"\n"}{end}' | grep "external-dns-private" | grep -- "--txt-owner-id=$aksEnvironmentName-active")
    if [ -n "$pod_exists" ]; then
        aksResourceGroup="$aksResourceGroupName"
        aksCluster="$aksClusterName"
        return 0
    else
        return 1
    fi
}

if check_pod_in_cluster; then
    echo "Pod with the specified argument found in cluster - $aksCluster."
    echo "----------- Setting Pipeline Variables -----------------"
    echo "##vso[task.setvariable variable=aksResourceGroup;isreadonly=true]$aksResourceGroup"
    echo "##vso[task.setvariable variable=aksCluster;isreadonly=true]$aksCluster"
else
    echo "Pod with the specified argument NOT found in cluster - $aksClusterName."
fi