#!/bin/bash
set -e

state_file_container_name=$1
storage_account_name=$2

echo "Check lease state on: $TERRAFORMSTATEFILE"
leaseExist=$(az storage blob show --container-name $state_file_container_name --name $TERRAFORMSTATEFILE --account-name $storage_account_name | jq -r '.properties.lease.state')

if [ ${leaseExist} = "leased" ]; then
  echo "Releasing lock on state file"
  az storage blob lease break --blob-name $TERRAFORMSTATEFILE --container-name $state_file_container_name --account-name $storage_account_name
else
  echo "No exiting lock on state file"
  exit 0
fi