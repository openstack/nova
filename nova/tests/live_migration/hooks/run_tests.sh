#!/bin/bash
# Live migration dedicated ci job will be responsible for testing different
# environments based on underlying storage, used for ephemerals.
# This hook allows to inject logic of environment reconfiguration in ci job.
# Base scenario for this would be:
#
# 1. test with all local storage (use default for volumes)
# 2. test with NFS for root + ephemeral disks
# 3. test with Ceph for root + ephemeral disks
# 4. test with Ceph for volumes and root + ephemeral disk

set -xe
cd $BASE/new/tempest

source $BASE/new/devstack/functions
source $BASE/new/devstack/functions-common
source $BASE/new/devstack/lib/nova
source $WORKSPACE/devstack-gate/functions.sh
source $BASE/new/nova/nova/tests/live_migration/hooks/utils.sh
source $BASE/new/nova/nova/tests/live_migration/hooks/nfs.sh
source $BASE/new/nova/nova/tests/live_migration/hooks/ceph.sh
primary_node=$(cat /etc/nodepool/primary_node_private)
SUBNODES=$(cat /etc/nodepool/sub_nodes_private)
SERVICE_HOST=$primary_node
STACK_USER=${STACK_USER:-stack}

echo '1. test with all local storage (use default for volumes)'
echo 'NOTE: test_volume_backed_live_migration is skipped due to https://bugs.launchpad.net/nova/+bug/1524898'
run_tempest "block migration test" "^.*test_live_migration(?!.*(test_volume_backed_live_migration))"

#all tests bellow this line use shared storage, need to update tempest.conf
echo 'disabling block_migration in tempest'
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=$BASE/new/tempest/etc/tempest.conf section=compute-feature-enabled option=block_migration_for_live_migration value=False"

echo '2. NFS testing is skipped due to setup failures with Ubuntu 16.04'
#echo '2. test with NFS for root + ephemeral disks'

#nfs_setup
#nfs_configure_tempest
#nfs_verify_setup
#run_tempest  "NFS shared storage test" "live_migration"
#nfs_teardown

echo '3. test with Ceph for root + ephemeral disks'
prepare_ceph
GLANCE_API_CONF=${GLANCE_API_CONF:-/etc/glance/glance-api.conf}
configure_and_start_glance

# Deal with grenade craziness...
if [ "$GRENADE_OLD_BRANCH" ]; then
    # NOTE(mriedem): Grenade runs in singleconductor mode, so it won't use
    # /etc/nova/nova-cpu.conf so we have to overwrite NOVA_CPU_CONF which is
    # read in configure_and_start_nova.
    if ! is_service_enabled n-super-cond; then
        NOVA_CPU_CONF=$NOVA_CONF
    fi
fi

configure_and_start_nova
run_tempest "Ceph nova&glance test" "^.*test_live_migration(?!.*(test_volume_backed_live_migration))"

set +e
#echo '4. test with Ceph for volumes and root + ephemeral disk'

#configure_and_start_cinder
#run_tempest "Ceph nova&glance&cinder test" "live_migration"
