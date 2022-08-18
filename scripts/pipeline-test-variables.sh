#!/bin/bash
set -e

if [ $ENVIRONMENT = 'sbox' ]; then
    DNS_ENVIRONMENT=sandbox
elif [ $ENVIRONMENT = 'ithc' ]; then
    DNS_ENVIRONMENT=ithc
elif [ $ENVIRONMENT = 'demo' ]; then
    DNS_ENVIRONMENT=demo
fi

if [ $PRODUCT = 'cft-platform' ]; then
    if [ $ENVIRONMENT = 'stg' ]; then
        DNS_ENVIRONMENT=aat
    elif [ $ENVIRONMENT = 'test' ]; then
        DNS_ENVIRONMENT=perftest
    fi
    if [ $COMPONENT = 'apim' ]; then
    APP_NAME=cft-api-mgmt
    else
    APP_NAME=plum
    fi
fi

if [ $PRODUCT = 'sds-platform' ]; then
    if [ $ENVIRONMENT = 'stg' ]; then
        DNS_ENVIRONMENT=staging
    elif [ $ENVIRONMENT = 'test' ]; then
        DNS_ENVIRONMENT=test
    fi
    if [ $COMPONENT = 'apim' ]; then
    APP_NAME=sds-api-mgmt
    else
    APP_NAME=toffee
    fi
fi

echo "##vso[task.setvariable variable=DNS_ENVIRONMENT]$DNS_ENVIRONMENT"
echo "##vso[task.setvariable variable=APP_NAME]$APP_NAME"