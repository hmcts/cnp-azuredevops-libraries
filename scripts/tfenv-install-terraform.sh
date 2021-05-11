#!/bin/bash
set -e

git clone https://github.com/tfutils/tfenv.git ~/.tfenv

sudo rm /usr/local/bin/terraform
sudo ln -s ~/.tfenv/bin/* /usr/local/bin

# Install and invoke use
echo "Installing Terraform based on version detected in .terraform-version file"
tfenv install | tee -a tfenv_install.log
cat tfenv_install.log | grep -i 'tfenv use' | cut -d "'" -f 2 > tfenv_use.sh
chmod a+x tfenv_use.sh
./tfenv_use.sh