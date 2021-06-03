#!/bin/bash
set -e

state_file_container_name=$1
storage_account_name=$2


# The state file key has a space e.g. UK South, using it as the --name parameter without
# escaping the white space makes the process see two inputs and treats every thing
# after the space e.g. South/... as another argument
state_file=$(echo TERRAFORMSTATEFILE | sed -e 's/ /\\ /')

echo "Checking lease state on: $state_file"
leaseExist=$(az storage blob show --container-name $state_file_container_name --name $state_file --account-name $storage_account_name | jq -r '.properties.lease.state')

echo "Current lease state: $leaseExist"

if [ ${leaseExist} = "leased" ]; then
  echo "Releasing lock on state file"
  az storage blob lease break --blob-name $state_file --container-name $state_file_container_name --account-name $storage_account_name
else
  echo "No exiting lock on state file"
  exit 0
fi