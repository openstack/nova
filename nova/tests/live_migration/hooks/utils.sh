#!/bin/bash

function run_tempest {
    local message=$1
    sudo -H -u tempest tox -eall -- --concurrency=$TEMPEST_CONCURRENCY live_migration
    exitcode=$?
    if [[ $exitcode -ne 0 ]]; then
      die $LINENO "$message failure"
    fi
}

function populate_start_script {
    SCREEN_NAME=${SCREEN_NAME:-stack}
    DEST=${DEST:-/opt/stack}
    SERVICE_DIR=${SERVICE_DIR:-${DEST}/status}
    ENABLED_SERVICES=${ENABLED_SERVICES:-n-cpu,g-api,c-vol}
    LIBVIRT_GROUP=${LIBVIRT_GROUP:-libvirtd}
    TIMESTAMP_FORMAT=${TIMESTAMP_FORMAT:-"%F-%H%M%S"}
    LOGDAYS=${LOGDAYS:-7}
    CURRENT_LOG_TIME=$(date "+$TIMESTAMP_FORMAT")

    #creates script for starting process without screen and copies it to all
    # nodes
    #
    # args:
    # $1 - service name to start
    # $2 - command to execute
    # $3 - group to run under
    cat > /tmp/start_process.sh <<EOF
set -x
service=\$1
command=\$2
sg=\$3
ENABLED_SERVICES=$ENABLED_SERVICES
SCREEN_NAME=$SCREEN_NAME
DEST=$DEST
SERVICE_DIR=$SERVICE_DIR
LOGDIR=$DEST/logs
TIMESTAMP_FORMAT=$TIMESTAMP_FORMAT
LOGDAYS=$LOGDAYS
CURRENT_LOG_TIME=\$(date "+$TIMESTAMP_FORMAT")
REAL_LOG_FILE="\$LOGDIR/\$service.log.\$CURRENT_LOG_TIME"
if [[ -n "\$LOGDIR" ]]; then
        exec 1>&"\$REAL_LOG_FILE" 2>&1
        ln -sf "\$REAL_LOG_FILE" \$LOGDIR/\$service.log
    export PYTHONUNBUFFERED=1
fi
if [[ -n "\$sg" ]]; then
    setsid sg \$sg -c "\$command" & echo \$! >\$SERVICE_DIR/\$SCREEN_NAME/\$service.pid
else
    setsid \$command & echo \$! >\$SERVICE_DIR/\$SCREEN_NAME/\$service.pid
fi
exit 0
EOF
    chmod +x /tmp/start_process.sh
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/start_process.sh dest=/tmp/start_process.sh owner=$STACK_USER group=$STACK_USER mode=0777"
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ls -la /tmp/start_process.sh"
}

function stop {
    local target=$1
    local service=$2
    $ANSIBLE $target --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "
executable=/bin/bash
BASE\=$BASE
source $BASE/new/devstack/functions-common
ENABLED_SERVICES\=$ENABLED_SERVICES
SCREEN_NAME\=$SCREEN_NAME
SERVICE_DIR\=$SERVICE_DIR
stop_process $service
"
}
