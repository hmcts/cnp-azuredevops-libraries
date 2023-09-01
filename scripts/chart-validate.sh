set -x

subscription=$1
businessArea=$2
environment=$3

az account set --subscription $subscription

check_pod_in_cluster() {
    local aks_rg="$businessArea-$subscription-00-rg"
    local aks_cluster="$businessArea-$subscription-00-aks"
    printf "\n\nTrying cluster $aks_cluster $aks_rg\n"
    az aks get-credentials \
        --resource-group "$aks_rg" \
        --name "$aks_cluster" --admin
    local pod_exists
    pod_exists=$(kubectl get pods --context "$aks_cluster-admin" -n admin -o jsonpath='{range .items[*]}{@.metadata.name}{"\t"}{@.spec.containers[0].args}{"\n"}{end}' | grep "external-dns-private" | grep -- "--txt-owner-id=preview-active")
    if [ -n "$pod_exists" ]; then
        aksResourceGroup="$aks_rg"
        aksCluster="$aks_cluster"
        return 0
    else
        echo "Pod with the specified argument not found in cluster $aks_cluster."
        return 1
    fi
}
aks_resource_group="$(businessArea)-$(environment)-00-rg"
aks_name="$(businessArea)-$(environment)-00-aks"
if check_pod_in_cluster "$aks_resource_group" "$aks_name"; then
    echo "Pod with the specified argument found in cluster $aks_name."
else
    aks_resource_group="$(businessArea)-$(environment)-01-rg"
    aks_name="$(businessArea)-$(environment)-01-aks"
    if check_pod_in_cluster "$aks_resource_group" "$aks_name"; then
        echo "Pod with the specified argument found in cluster $aks_name."
    else
        echo "Pod with the specified argument not found in any clusters."
        echo "##vso[task.complete result=Failed;]Pod not found in any clusters."
    fi
fi
echo "##vso[task.setvariable variable=aksResourceGroup;isOutput=true]$aksResourceGroup"
echo "##vso[task.setvariable variable=aksCluster;isOutput=true]$aksCluster"