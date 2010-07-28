#!/bin/bash 

venv=.nova-venv
with_venv=tools/with_venv.sh

if [ -e ${venv} ]; then
  ${with_venv} python run_tests.py
else  
  echo "You need to install the Nova virtualenv before you can run this."
  echo ""
  echo "Please run tools/install_venv.py"
  exit 1
fi
