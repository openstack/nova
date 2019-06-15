#!/bin/sh
#
# A simple wrapper around flake8 which makes it possible
# to ask it to only verify files changed in the current
# git HEAD patch.
#
# Intended to be invoked via tox:
#
#   tox -epep8 -- -HEAD
#

if test "x$1" = "x-HEAD" ; then
    shift
    files=$(git diff --name-only HEAD~1 | tr '\n' ' ')
    echo "Running flake8 on ${files}"
    echo ""
    echo "Consider using the 'pre-commit' tool instead."
    echo ""
    echo "    pip install --user pre-commit"
    echo "    pre-commit install --allow-missing-config"
    echo ""
    diff -u --from-file /dev/null ${files} | flake8 --diff "$@"
else
    echo "Running flake8 on all files"
    echo ""
    exec flake8 "$@"
fi
