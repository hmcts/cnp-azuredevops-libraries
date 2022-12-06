#!/bin/bash
set -e
organization="hmcts"
project="$SYSTEM_TEAMPROJECT"
link="https://dev.azure.com/$organization/$project/_apis/build/builds?api-version=5.1&definitions=$pipelinedefinition"
requestlink=${link/' '/'%20'}
echo "This is build $thisbuild"
IFS=$'\n'
JSON_DATA=($(curl -s -u :"$azuredevopstoken" --request GET "$requestlink" -H "Content-Type: application/json" | jq  '.value[] | .status + (.id|tostring)' | sort -u | grep inProgress))
buildnumber=(${JSON_DATA//[!0-9]/})


if [ $thisbuild -eq $buildnumber ]
then

echo "No other builds are in Progress"

else

while [[ $thisbuild -ne $buildnumber_inprogress ]]
do

IFS=$'\n'
JSON_CHECK=($(curl -s -u :"$azuredevopstoken" --request GET "$requestlink" -H "Content-Type: application/json" | jq  '.value[] | .status + (.id|tostring)' | sort -u | grep inProgress))
buildnumberrunning=(${JSON_CHECK//[!0-9]/})
echo "Build number: $buildnumberrunning is in progress"

buildnumber_inprogress=$buildnumberrunning
sleep 10

done

fi

echo "Starting $thisbuild"