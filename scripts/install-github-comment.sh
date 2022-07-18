#!/bin/bash

GH_COMMENT_VERSION=v4.2.0

curl -fL -o tfcmt.tar.gz https://github.com/suzuki-shunsuke/tfcmt/releases/download/$GH_COMMENT_VERSION/tfcmt_linux_amd64.tar.gz
tar -C /usr/bin -xzf ./tfcmt.tar.gz