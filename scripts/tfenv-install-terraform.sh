#!/bin/bash
set -e


if [ -f "~/.tfenv" ]; then
  rm -rf ~/.tfenv
fi

git clone https://github.com/tfutils/tfenv.git ~/.tfenv

if [ ! -f "/usr/bin/sudo" ]; then
  apt install -y sudo
fi

if [ -f "/usr/local/bin/terraform" ]; then
  sudo rm /usr/local/bin/terraform
fi

sudo ln -s ~/.tfenv/bin/* /usr/local/bin

# Install and invoke use
echo "Installing Terraform based on version detected in .terraform-version file"
tfenv install | tee -a tfenv_install.log
cat tfenv_install.log | grep -i 'tfenv use' | cut -d "'" -f 2 > tfenv_use.sh
chmod a+x tfenv_use.sh
./tfenv_use.sh