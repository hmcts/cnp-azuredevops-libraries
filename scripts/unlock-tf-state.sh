#!/bin/bash
set -e

storage_account_name=$1
stateFilePath=$2
container=${3:-subscription-tfstate}

if az account list | grep "HMCTS-CONTROL"
then
  subscription="HMCTS-CONTROL"
else
  subscription="DCD-RBAC-CONTROL"
fi

az account set --subscription $subscription

export AZURE_STORAGE_KEY=$(az storage account keys list  -n $storage_account_name --query [0].value -o tsv)

leaseExist=`az storage blob show --container-name ${container} --name "${stateFilePath}" --account-name $storage_account_name | jq -r '.properties.lease.state'`

if [ ${leaseExist} = "leased" ]; then
  az storage blob lease break --blob-name "${stateFilePath}" --container-name ${container} --account-name $storage_account_name
else
exit 0
fi
