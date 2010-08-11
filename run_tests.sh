#!/bin/bash 

venv=.nova-venv
with_venv=tools/with_venv.sh

if [ -e ${venv} ]; then
  ${with_venv} python run_tests.py $@
else  
  echo "No virtual environment found...creating one"
  python tools/install_venv.py
  ${with_venv} python run_tests.py $@
fi
