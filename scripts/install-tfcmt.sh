#!/bin/bash
set -euo pipefail

TFCMT_VERSION=v4.14.12

curl -fL --retry 5 --retry-delay 5 --retry-all-errors -o tfcmt.tar.gz https://github.com/suzuki-shunsuke/tfcmt/releases/download/$TFCMT_VERSION/tfcmt_linux_amd64.tar.gz

if command -v sudo &> /dev/null
then
    sudo tar -C /usr/bin -xzf ./tfcmt.tar.gz tfcmt
else
  tar -C /usr/bin -xzf ./tfcmt.tar.gz tfcmt
fi
