#!/bin/bash

function run_tempest {
    local message=$1
    local tempest_regex=$2
    # NOTE(gmann): Use branch constraint because Tempest is pinned to the branch release
    # instead of using master. We need to export it via env var UPPER_CONSTRAINTS_FILE
    # so that initial creation of tempest tox use stable branch constraint
    # instead of master constraint which is hard coded in tempest/tox.ini
    export UPPER_CONSTRAINTS_FILE=$BASE/new/requirements/upper-constraints.txt

    sudo -H -u tempest UPPER_CONSTRAINTS_FILE=$UPPER_CONSTRAINTS_FILE tox -eall -- $tempest_regex --concurrency=$TEMPEST_CONCURRENCY
    exitcode=$?
    if [[ $exitcode -ne 0 ]]; then
      die $LINENO "$message failure"
    fi
}
