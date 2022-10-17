#!/bin/bash

TFCMT_VERSION=v4.0.0

curl -fL -o tfcmt.tar.gz https://github.com/suzuki-shunsuke/tfcmt/releases/download/$TFCMT_VERSION/tfcmt_linux_amd64.tar.gz

if command -v sudo &> /dev/null
then
    sudo tar -C /usr/bin -xzf ./tfcmt.tar.gz tfcmt
else
  tar -C /usr/bin -xzf ./tfcmt.tar.gz tfcmt
fi
