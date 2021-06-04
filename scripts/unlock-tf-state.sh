#!/bin/bash
set -e

storage_account_name=$1
stateFilePath=$2

leaseExist=`az storage blob show --container-name subscription-tfstate --name "${stateFilePath}" --account-name $storage_account_name | jq -r '.properties.lease.state'`

if [ ${leaseExist} = "leased" ]; then
  az storage blob lease break --blob-name "${stateFilePath}" --container-name subscription-tfstate --account-name $storage_account_name
else
exit 0
fi
