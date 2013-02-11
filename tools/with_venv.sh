#!/bin/bash
tools_path=${tools_path:-$(dirname $0)}
venv_path=${venv_path:-${tools_path}}
venv_dir=${venv_name:-/../.venv}
TOOLS=${tools_path}
VENV=${venv:-${venv_path}/${venv_dir}}
source ${VENV}/bin/activate && "$@"
