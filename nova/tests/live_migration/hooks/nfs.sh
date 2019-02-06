#!/bin/bash

function nfs_setup {
    if uses_debs; then
        module=apt
    elif is_fedora; then
        module=yum
    fi
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m $module \
            -a "name=nfs-common state=present"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m $module \
            -a "name=nfs-kernel-server state=present"

    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=/etc/idmapd.conf section=Mapping option=Nobody-User value=nova"

    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=/etc/idmapd.conf section=Mapping option=Nobody-Group value=nova"

    for SUBNODE in $SUBNODES ; do
        $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m lineinfile -a "dest=/etc/exports line='/opt/stack/data/nova/instances $SUBNODE(rw,fsid=0,insecure,no_subtree_check,async,no_root_squash)'"
    done

    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "exportfs -a"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m service -a "name=nfs-kernel-server state=restarted"
    GetDistro
    if [[ ! ${DISTRO} =~ (xenial) ]]; then
        $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m service -a "name=idmapd state=restarted"
    fi
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p tcp --dport 111 -j ACCEPT"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p udp --dport 111 -j ACCEPT"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p tcp --dport 2049 -j ACCEPT"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "iptables -A INPUT -p udp --dport 2049 -j ACCEPT"
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "mount -t nfs4 -o proto\=tcp,port\=2049 $primary_node:/ /opt/stack/data/nova/instances/"
}

function nfs_configure_tempest {
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=$BASE/new/tempest/etc/tempest.conf section=compute-feature-enabled option=block_migration_for_live_migration value=False"
}

function nfs_verify_setup {
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m file -a "path=/opt/stack/data/nova/instances/test_file state=touch"
    if [ ! -e '/opt/stack/data/nova/instances/test_file' ]; then
        die $LINENO "NFS configuration failure"
    fi
}

function nfs_teardown {
    #teardown nfs shared storage
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "umount -t nfs4 /opt/stack/data/nova/instances/"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m service -a "name=nfs-kernel-server state=stopped"
}