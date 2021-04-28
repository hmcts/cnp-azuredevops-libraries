#!/bin/bash
set -e

component=$1
storage_account_name=$2

leaseExist=`az storage blob show --container-name tfstate --name $component.tfstate --account-name $storage_account_name | jq -r '.properties.lease.state'`

if [ ${leaseExist} = "leased" ]; then
az storage blob lease break --blob-name $component.tfstate --container-name tfstate --account-name $storage_account_name
else
exit 0
fi