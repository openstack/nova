#!/bin/bash -x

MANAGE="/usr/local/bin/nova-manage"

function archive_deleted_rows {
    # NOTE(danms): Run this a few times to make sure that we end
    # up with nothing more to archive
    for i in `seq 30`; do
        $MANAGE db archive_deleted_rows --verbose --max_rows 1000
        RET=$?
        if [[ $RET -gt 1 ]]; then
            echo Archiving failed with result $RET
            return $RET
        elif [[ $RET -eq 0 ]]; then
            echo Archiving Complete
            break;
        fi
    done
}

archive_deleted_rows
