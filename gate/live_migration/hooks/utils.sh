#!/bin/bash

function run_tempest {
    local message=$1
    local tempest_regex=$2

    # NOTE(gmann): Set upper constraint for Tempest run so that it matches
    # with what devstack is using and does not recreate the tempest virtual
    # env.
    TEMPEST_VENV_UPPER_CONSTRAINTS=$(set +o xtrace &&
        source $BASE/new/devstack/stackrc &&
        echo $TEMPEST_VENV_UPPER_CONSTRAINTS)
    export UPPER_CONSTRAINTS_FILE=$TEMPEST_VENV_UPPER_CONSTRAINTS
    echo "using $UPPER_CONSTRAINTS_FILE for tempest run"

    sudo -H -u tempest UPPER_CONSTRAINTS_FILE=$UPPER_CONSTRAINTS_FILE tox -eall -- $tempest_regex --concurrency=$TEMPEST_CONCURRENCY
    exitcode=$?
    if [[ $exitcode -ne 0 ]]; then
      die $LINENO "$message failure"
    fi
}
