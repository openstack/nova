#!/bin/bash -x

# Do some performance related information gathering for placement.
EXPLANATION="
This output combines output from placeload with timing information
gathered via curl. The placeload output is the current maximum
microversion of placement followed by an encoded representation of
what it has done. Lowercase 'r', 'i', 'a', and 't' indicate successful
creation of a resource provider and setting inventory, aggregates, and
traits on that resource provider.

If there are upper case versions of any of those letters, a failure
happened for a single request. The letter will be followed by the
HTTP status code and the resource provider uuid. These can be used
to find the relevant entry in logs/screen-placement-api.txt.gz.

Note that placeload does not exit with an error code when this
happens. It merely reports and moves on. Under correct circumstances
the right output is a long string of 4000 characters containing
'r', 'i', 'a', 't' in random order (because async).

After that are three aggregate uuids, and then the output
of two timed curl requests.

If no timed requests are present it means that the expected number
of resource providers were not created. At this time, only resource
providers are counted, not whether they have the correct inventory,
aggregates, or traits.

"


# This aggregate uuid is a static value in placeload.
AGGREGATE="14a5c8a3-5a99-4e8f-88be-00d85fcb1c17"
TRAIT="HW_CPU_X86_AVX2"
PLACEMENT_QUERY="resources=VCPU:1,DISK_GB:10,MEMORY_MB:256&member_of=${AGGREGATE}&required=${TRAIT}"

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
    pip install 'placeload==0.3.0'

    # Turn off keystone auth
    iniset -sudo $NOVA_CONF DEFAULT auth_strategy noauth2
    restart_service devstack@placement-api

    # get placement endpoint
    placement_url=$(get_endpoint_url placement public)

    # load with placeload
    (
        echo "$EXPLANATION"
        placeload $placement_url $COUNT
    ) | tee -a $LOG
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
