#!/bin/bash
set -e

if [ $ENVIRONMENT = 'sbox' ]; then
    ENVIRONMENT=sandbox
fi

if [ $PRODUCT = 'cft-platform' ]; then
    if [ $ENVIRONMENT = 'stg' ]; then
        ENVIRONMENT=aat
    elif [ $ENVIRONMENT = 'test' ]; then
        ENVIRONMENT=perftest
    fi
    APP_NAME=plum
fi

if [ $PRODUCT = 'sds-platform' ]; then
    if [ $ENVIRONMENT = 'stg' ]; then
        ENVIRONMENT=staging
    fi
    APP_NAME=toffee
fi

echo "##vso[task.setvariable variable=ENVIRONMENT;isOutput=true]true"
echo "##vso[task.setvariable variable=APP_NAME;isOutput=true]true"