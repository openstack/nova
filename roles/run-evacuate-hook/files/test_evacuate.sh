#!/bin/bash
# Source tempest to determine the build timeout configuration.
source /opt/stack/devstack/lib/tempest
source /opt/stack/devstack/openrc admin
set -x
set -e

# Wait for the controller compute service to be enabled.
count=0
status=$(openstack compute service list --host ${CONTROLLER_HOSTNAME} --service nova-compute -f value -c Status)
while [ "${status}" != "enabled" ]
do
    sleep 1
    count=$((count+1))
    if [ ${count} -eq 30 ]; then
        echo "Timed out waiting for controller compute service to be enabled"
        exit 5
    fi
    status=$(openstack compute service list --host ${CONTROLLER_HOSTNAME} --service nova-compute -f value -c Status)
done

function evacuate_and_wait_for_active() {
    local server="$1"

    nova evacuate ${server}
    # Wait for the instance to go into ACTIVE state from the evacuate.
    count=0
    status=$(openstack server show ${server} -f value -c status)
    while [ "${status}" != "ACTIVE" ]
    do
        sleep 1
        count=$((count+1))
        if [ ${count} -eq ${BUILD_TIMEOUT} ]; then
            echo "Timed out waiting for server ${server} to go to ACTIVE status"
            exit 6
        fi
        status=$(openstack server show ${server} -f value -c status)
    done
}

evacuate_and_wait_for_active evacuate-test
evacuate_and_wait_for_active evacuate-bfv-test

# Make sure the servers moved.
for server in evacuate-test evacuate-bfv-test; do
    host=$(openstack server show ${server} -f value -c OS-EXT-SRV-ATTR:host)
    if [[ ${host} != ${CONTROLLER_HOSTNAME} ]]; then
        echo "Unexpected host ${host} for server ${server} after evacuate."
        exit 7
    fi
done

# Cleanup test servers
openstack server delete --wait evacuate-test
openstack server delete --wait evacuate-bfv-test
