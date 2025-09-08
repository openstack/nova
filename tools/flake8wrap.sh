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
    files=$(git diff --name-only HEAD~1 | grep '.py$' | tr '\n' ' ')
    echo "Running flake8 on ${files}"
    echo ""
    flake8 "$@" $files
else
    echo "Running flake8 on all files"
    echo ""
    exec flake8 "$@"
fi
