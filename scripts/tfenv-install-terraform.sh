#!/bin/bash
set -e

rm -rf ~/.tfenv

TFENV_VERSION=$1

if [ -z "$TFENV_VERSION" ]; then
  echo "TFENV_VERSION is not set. Setting to default"
  TFENV_VERSION="v3.0.0"
else
  echo "TFENV_VERSION is set to $TFENV_VERSION"
fi

git clone -b "$TFENV_VERSION" --single-branch https://github.com/tfutils/tfenv.git ~/.tfenv

if [ $(whoami) == "root" ]; then
  ln -s -f ~/.tfenv/bin/* /usr/local/bin
else
  mkdir -p ~/.local/bin
  ln -s -f ~/.tfenv/bin/* ~/.local/bin
fi

. ~/.profile

# Install and invoke use
echo "Installing Terraform based on version detected in .terraform-version file"
tfenv install | tee tfenv_install.log
cat tfenv_install.log | grep -i 'tfenv use' | cut -d "'" -f 2 > tfenv_use.sh
chmod a+x tfenv_use.sh
./tfenv_use.sh
