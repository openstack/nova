#!/bin/bash

function run_tempest {
    local message=$1
    local tempest_regex=$2
    sudo -H -u tempest tox -eall -- $tempest_regex --concurrency=$TEMPEST_CONCURRENCY
    exitcode=$?
    if [[ $exitcode -ne 0 ]]; then
      die $LINENO "$message failure"
    fi
}
