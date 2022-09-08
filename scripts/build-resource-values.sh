#!/bin/bash
# This script is used to dynamically set some pipeline values
set -e

MULTI_REGION=$1
ENVIRONMENT=$2
COMPONENT=$3
LOCATION=$4

TF_PLAN_NAME="$ENVIRONMENT-$COMPONENT"
TF_VARS_NAME="$ENVIRONMENT"

formatted_location=$(echo "$LOCATION" | tr "[:upper:]" "[:lower:]" | tr -d "[:space:]")

if [[ $MULTI_REGION == true ]]; then
TF_PLAN_NAME="$ENVIRONMENT-$formatted_location-$COMPONENT"
TF_VARS_NAME="$ENVIRONMENT-$formatted_location"
fi

echo "##vso[task.setvariable variable=tfPlanName]$TF_PLAN_NAME"
echo "##vso[task.setvariable variable=tfVarsName]$TF_VARS_NAME"