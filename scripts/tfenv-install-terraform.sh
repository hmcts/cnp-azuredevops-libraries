#!/bin/bash
set -e

git clone https://github.com/tfutils/tfenv.git ~/.tfenv

sudo ln -s ~/.tfenv/bin/* /usr/local/bin

# run 'tfenv use version' as tfenv version > 1.0.2 currently does not auto switch to use installed version
echo "Installing Terraform based on minimum required version detected"
tfenv install min-required | tee -a tfenv_install.log
cat tfenv_install.log | grep -i 'tfenv use' | cut -d "'" -f 2 > tfenv_use.sh
chmod a+x tfenv_use.sh
./tfenv_use.sh