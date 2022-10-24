#!/bin/bash
set -e

rm -rf ~/.tfenv
git clone -b v3.0.0 --single-branch https://github.com/tfutils/tfenv.git ~/.tfenv

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
