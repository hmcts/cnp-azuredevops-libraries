#!/bin/bash
set -e

state_file_container_name=$1
storage_account_name=$2

echo "Check state lock on: $TERRAFORMSTATEFILE"
leaseExist=$(az storage blob show --container-name $state_file_container_name --name $TERRAFORMSTATEFILE --account-name $storage_account_name | jq -r '.properties.lease.state')

echo "Current lease state: $leaseExist"

if [ ${leaseExist} = "leased" ]; then
az storage blob lease break --blob-name $TERRAFORMSTATEFILE --container-name $state_file_container_name --account-name $storage_account_name
else
exit 0
fi