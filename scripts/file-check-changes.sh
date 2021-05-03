#!/bin/bash
set -e

FILES=($files_list)
CHANGED_FILES=$(git diff HEAD HEAD~ --name-only)
MATCH_COUNT=0

echo $CHANGED_FILES
for PATH_FILTER in ${FILES[@]}
do

echo "Checking for changes in in $PATH_FILTER"
for FILE in $CHANGED_FILES
do
if [[ $FILE == *$PATH_FILTER* ]]; then

MATCH_FOUND=true
MATCH_COUNT=$(($MATCH_COUNT+1))
MATCHES+=($FILE)

fi
done

done

echo "$MATCH_COUNT match(es) for filters '${MATCHES[@]}' found."

if [[ $MATCH_COUNT -gt 0 ]]; then

echo "##vso[task.setvariable variable=SOURCE_CODE_CHANGED;isOutput=true]true"

else

echo "##vso[task.setvariable variable=SOURCE_CODE_CHANGED;isOutput=true]false"

fi