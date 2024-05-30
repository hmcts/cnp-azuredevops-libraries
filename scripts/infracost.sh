#!/bin/bash

# Install Infracost CLI
curl -fsSL https://github.com/infracost/infracost/releases/latest/download/infracost-$(uname -s)-$(uname -m).tar.gz | tar -xzf - -C /tmp
sudo mv /tmp/infracost-$(uname -s)-$(uname -m) /usr/local/bin/infracost

# Verify installation
infracost --version

# checkout master
git checkout $MASTER_BRANCH

# configure infracost
infracost configure set --api-key $INFRACOST_API_KEY
infracost configure set currency=$INFRACOST_CURRENCY

# generate infracost base
infracost breakdown --path=. --format=json --out-file=/tmp/infracost-base.json

# checkout PR branch
git checkout $PULL_REQUEST_BRANCH

# generate infracost diff
infracost diff --path=. --format=json --compare-to=/tmp/infracost-base.json

# comment on pr

infracost comment github \
    --path=/tmp/infracost.json \
    --github-token=$GITHUB_TOKEN \
    --pull-request=$PULL_REQUEST_BRANCH \
    --repo=$REPO_NAME \
    --behavior=update
