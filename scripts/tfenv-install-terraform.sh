#!/bin/bash
set -e

if [ -d "~/.tfenv" ]; then
  rm -rf ~/.tfenv/
fi

git clone -b v2.2.2 --single-branch https://github.com/tfutils/tfenv.git ~/.tfenv

mkdir -p ~/.local/bin
ln -s ~/.tfenv/bin/* ~/.local/bin
echo 'export PATH="$HOME/.tfenv/bin:$PATH"' >> ~/.bashrc
. ~/.bashrc
which tfenv

# Install and invoke use
echo "Installing Terraform based on version detected in .terraform-version file"
tfenv install | tee -a tfenv_install.log
cat tfenv_install.log | grep -i 'tfenv use' | cut -d "'" -f 2 > tfenv_use.sh
chmod a+x tfenv_use.sh
./tfenv_use.sh
