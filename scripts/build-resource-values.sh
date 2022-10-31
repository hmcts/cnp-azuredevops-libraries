#!/bin/bash
###########################################################################################
# This script is used to dynamically set some pipeline values
# Values below are passed in via the pipeline step.

#   MULTI_REGION
#   ENVIRONMENT
#   COMPONENT
#   LOCATION
#------------------------------------------------------------------------------------------

set -e

TF_PLAN_NAME="$ENVIRONMENT-$COMPONENT"
TF_VARS_NAME="$ENVIRONMENT"

formatted_location=$(echo "$LOCATION" | tr "[:upper:]" "[:lower:]" | tr -d "[:space:]")

if [[ $COMPONENT == acme ]]; then
  TF_PLAN_NAME="$ENVIRONMENT-$STAGE-$COMPONENT"
fi

if [[ $MULTI_REGION == True ]]; then
  TF_PLAN_NAME="$ENVIRONMENT-$formatted_location-$COMPONENT"
  TF_VARS_NAME="$formatted_location"
fi

echo "##vso[task.setvariable variable=tfPlanName]$TF_PLAN_NAME"
echo "##vso[task.setvariable variable=tfVarsName]$TF_VARS_NAME"
