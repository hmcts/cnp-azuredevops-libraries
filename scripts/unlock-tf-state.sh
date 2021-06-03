#!/bin/bash
set -e

terraform_state_file="$1"
state_file_container_name=$2
storage_account_name=$3

echo "State file: $TERRAFORMSTATEFILE"

leaseExist=$(az storage blob show --container-name $state_file_container_name --name $terraform_state_file --account-name $storage_account_name | jq -r '.properties.lease.state')

echo "Current lease state: $leaseExist"

if [ ${leaseExist} = "leased" ]; then
az storage blob lease break --blob-name $terraform_state_file --container-name $state_file_container_name --account-name $storage_account_name
else
exit 0
fi