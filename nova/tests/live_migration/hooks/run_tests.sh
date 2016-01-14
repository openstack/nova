#!/bin/bash
# Live migration dedicated ci job will be responsible for testing different
# environments based on underlying storage, used for ephemerals.
# This hook allows to inject logic of environment reconfiguration in ci job.
# Base scenario for this would be:
# - run live-migration on env without shared storage
# - set up ceph for ephemerals, and reconfigure nova, tempest for that
# - run live-migration tests
# - remove ceph and set up nfs for ephemerals, make appropriate change in nova
# and tempest config
# - run live-migration tests

set -x
cd $BASE/new/tempest
sudo -H -u tempest tox -eall -- --concurrency=$TEMPEST_CONCURRENCY live_migration

#nfs preparation
echo "subnode info:"
cat /etc/nodepool/sub_nodes_private
echo "inventory:"
cat $WORKSPACE/inventory
echo "process info:"
ps aux | grep nova-compute
source $WORKSPACE/devstack-gate/functions.sh

if uses_debs; then
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m apt \
            -a "name=nfs-common state=present"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m apt \
            -a "name=nfs-kernel-server state=present"
elif is_fedora; then
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m yum \
            -a "name=nfs-common state=present"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m yum \
            -a "name=nfs-kernel-server state=present"
fi

$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=/etc/idmapd.conf section=Mapping option=Nobody-User value=nova"

$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=/etc/idmapd.conf section=Mapping option=Nobody-Group value=nova"

SUBNODES=$(cat /etc/nodepool/sub_nodes_private)
for SUBNODE in $SUBNODES ; do
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m lineinfile -a "dest=/etc/exports line='/opt/stack/data/nova/instances $SUBNODE(rw,fsid=0,insecure,no_subtree_check,async,no_root_squash)'"
done

$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "exportfs -a"
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m service -a "name=nfs-kernel-server state=restarted"
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m service -a "name=idmapd state=restarted"
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p tcp --dport 111 -j ACCEPT"
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p udp --dport 111 -j ACCEPT"
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p tcp --dport 2049 -j ACCEPT"
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p udp --dport 2049 -j ACCEPT"
primary_node=$(cat /etc/nodepool/primary_node_private)
$ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "mount -t nfs4 -o proto\=tcp,port\=2049 $primary_node:/ /opt/stack/data/nova/instances/"
$ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m file -a "path=/opt/stack/data/nova/instances/test_file state=touch"
echo "check whether NFS shared storage works or not:"
ls -la /opt/stack/data/nova/instances
SCREEN_NAME=${SCREEN_NAME:-stack}
$ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=$BASE/new/tempest/etc/tempest.conf section=compute-feature-enabled option=block_migration_for_live_migration value=False"

sudo -H -u tempest tox -eall -- --concurrency=$TEMPEST_CONCURRENCY live_migration
