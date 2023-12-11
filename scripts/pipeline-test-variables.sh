#!/bin/bash
set -e

if [ $ENVIRONMENT = 'sbox' ]; then
    DNS_ENVIRONMENT='.sandbox'
elif [ $ENVIRONMENT = 'ithc' ]; then
    DNS_ENVIRONMENT='.ithc'
elif [ $ENVIRONMENT = 'demo' ]; then
    DNS_ENVIRONMENT='.demo'
fi

if [ $PRODUCT = 'cft-platform' ]; then
    if [ $ENVIRONMENT = 'stg' ]; then
        DNS_ENVIRONMENT='.aat'
    elif [ $ENVIRONMENT = 'test' ]; then
        DNS_ENVIRONMENT='.perftest'
    fi
    APP_NAME=plum
    APIM_NAME=cft-api-mgmt
fi

if [ $PRODUCT = 'sds-platform' ]; then
    if [ $ENVIRONMENT = 'stg' ]; then
        DNS_ENVIRONMENT='.staging'
    elif [ $ENVIRONMENT = 'test' ]; then
        DNS_ENVIRONMENT='.test'
    fi
    APP_NAME=toffee
    APIM_NAME=sds-api-mgmt
fi

echo "##vso[task.setvariable variable=DNS_ENVIRONMENT]$DNS_ENVIRONMENT"
echo "##vso[task.setvariable variable=APP_NAME]$APP_NAME"
echo "##vso[task.setvariable variable=APIM_NAME]$APIM_NAME"