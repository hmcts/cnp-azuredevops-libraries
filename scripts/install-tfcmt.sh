#!/bin/bash

BASE_URL=https://github.com/suzuki-shunsuke/tfcmt/releases/download
DOWNLOAD_URL="${BASE_URL}/v${TFCMT_VERSION}/tfcmt_linux_amd64.tar.gz"
TFCMT_VERSION=3.2.1
wget ${DOWNLOAD_URL} -P /tmp
tar zxvf /tmp/tfcmt_linux_amd64.tar.gz -C /tmp
mv /tmp/tfcmt /usr/local/bin/tfcmt