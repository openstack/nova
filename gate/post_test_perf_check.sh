#!/bin/bash -x

# Do some performance related information gathering for placement.

# This aggregate uuid is a static value in placeload.
AGGREGATE="14a5c8a3-5a99-4e8f-88be-00d85fcb1c17"
PLACEMENT_QUERY="resources=VCPU:1,DISK_GB:10,MEMORY_MB:256&member_of=${AGGREGATE}"

BASE=${BASE:-/opt/stack}
source ${BASE}/new/devstack/functions
source ${BASE}/new/devstack/lib/nova
source ${BASE}/new/devstack/lib/placement
# Putting the log here ought to mean it is automatically gathered by zuul
LOG=${BASE}/logs/placement-perf.txt
COUNT=1000

function check_placement {
    local placement_url
    local rp_count

    python -m virtualenv -p python3 .placeload
    . .placeload/bin/activate

    # install placeload
    pip install placeload

    # Turn off keystone auth
    iniset -sudo $NOVA_CONF DEFAULT auth_strategy noauth2
    restart_service devstack@placement-api

    # get placement endpoint
    placement_url=$(get_endpoint_url placement public)

    # load with placeload
    placeload $placement_url $COUNT | tee -a $LOG
    rp_count=$(curl -H 'x-auth-token: admin' $placement_url/resource_providers |json_pp|grep -c '"name"')
    # Skip curl and note if we failed to create the required number of rps
    if [[ $rp_count -ge $COUNT ]]; then
        (
            echo '##### TIMING GET /allocation_candidates'
            time curl -s -H 'x-auth-token: admin' -H 'openstack-api-version: placement 1.21' "$placement_url/allocation_candidates?${PLACEMENT_QUERY}" > /dev/null
            time curl -s -H 'x-auth-token: admin' -H 'openstack-api-version: placement 1.21' "$placement_url/allocation_candidates?${PLACEMENT_QUERY}" > /dev/null
        ) 2>&1 | tee -a $LOG
    else
        (
            echo "Unable to create expected number of resource providers. Expected: ${COUNT}, Got: $rp_count"
            echo "See job-output.txt.gz and logs/screen-placement-api.txt.gz for additional detail."
        ) | tee -a $LOG
    fi
    deactivate
}

# Be admin
set +x
source $BASE/new/devstack/openrc admin
set -x
check_placement
