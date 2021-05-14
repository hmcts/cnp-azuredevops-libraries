#!/bin/bash
set -e

git clone -b v2.2.2 --single-branch https://github.com/tfutils/tfenv.git ~/.tfenv

mkdir -p ~/.local/bin
. ~/.profile
ln -s ~/.tfenv/bin/* ~/.local/bin
PATH="$HOME/.local/bin:$PATH"
which tfenv

# Install and invoke use
echo "Installing Terraform based on version detected in .terraform-version file"
tfenv install | tee -a tfenv_install.log
cat tfenv_install.log | grep -i 'tfenv use' | cut -d "'" -f 2 > tfenv_use.sh
chmod a+x tfenv_use.sh
./tfenv_use.sh