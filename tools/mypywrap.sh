#!/bin/sh
#
# A wrapper around mypy that allows us to specify what files to run 'mypy' type
# checks on. Intended to be invoked via tox:
#
#   tox -e mypy
#
# Eventually this should go away once we have either converted everything or
# converted enough and ignored [1] the rest.
#
# [1] http://mypy.readthedocs.io/en/latest/config_file.html#per-module-flags

ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

if [ $# -eq 0 ]; then
    # if no arguments provided, use the standard converted lists
    lines=$(grep -v '#' $ROOT_DIR/../mypy-files.txt)
    python -m mypy ${lines[@]}
else
    # else test what the user asked us to
    python -m mypy $@
fi
