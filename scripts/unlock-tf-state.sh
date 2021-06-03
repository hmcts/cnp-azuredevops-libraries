#!/bin/bash
set -e

state_file_container_name=$1
storage_account_name=$2

echo "Check lease state on: $TERRAFORMSTATEFILE"

# The state file location has a space e.g. UK South, this confuses the process,
# escaping the white space seems to cut it
state_file=$(echo TERRAFORMSTATEFILE | sed -e 's/ /\\ /')
leaseExist=$(az storage blob show --container-name $state_file_container_name --name $state_file --account-name $storage_account_name | jq -r '.properties.lease.state')

echo "Current lease state: $leaseExist"

if [ ${leaseExist} = "leased" ]; then
  echo "Releasing lock on state file"
  az storage blob lease break --blob-name $state_file --container-name $state_file_container_name --account-name $storage_account_name
else
  exit 0
fi