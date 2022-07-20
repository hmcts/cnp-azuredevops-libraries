#!/bin/bash

TFCMT_VERSION=v3.2.1

curl -fL -o tfcmt.tar.gz https://github.com/suzuki-shunsuke/tfcmt/releases/download/$TFCMT_VERSION/tfcmt_linux_amd64.tar.gz
sudo tar -C /usr/bin -xzf ./tfcmt.tar.gz tfcmt

buildRepo=$(echo "$Build.Repository.Name" | cut -d '/' -f 2)