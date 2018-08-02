#!/bin/bash

function prepare_ceph {
    git clone git://git.openstack.org/openstack/devstack-plugin-ceph /tmp/devstack-plugin-ceph
    source /tmp/devstack-plugin-ceph/devstack/settings
    source /tmp/devstack-plugin-ceph/devstack/lib/ceph
    install_ceph
    configure_ceph
    #install ceph-common package on compute nodes
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m raw -a "executable=/bin/bash
    source $BASE/new/devstack/functions
    source $BASE/new/devstack/functions-common
    git clone git://git.openstack.org/openstack/devstack-plugin-ceph /tmp/devstack-plugin-ceph
    source /tmp/devstack-plugin-ceph/devstack/lib/ceph
    install_ceph_remote
    "

    #copy ceph admin keyring to compute nodes
    sudo cp /etc/ceph/ceph.client.admin.keyring /tmp/ceph.client.admin.keyring
    sudo chown ${STACK_USER}:${STACK_USER} /tmp/ceph.client.admin.keyring
    sudo chmod 644 /tmp/ceph.client.admin.keyring
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.client.admin.keyring dest=/etc/ceph/ceph.client.admin.keyring owner=ceph group=ceph"
    sudo rm -f /tmp/ceph.client.admin.keyring
    #copy ceph.conf to compute nodes
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/etc/ceph/ceph.conf dest=/etc/ceph/ceph.conf owner=root group=root"

    start_ceph
}

function _ceph_configure_glance {
    GLANCE_API_CONF=${GLANCE_API_CONF:-/etc/glance/glance-api.conf}
    sudo ceph -c ${CEPH_CONF_FILE} osd pool create ${GLANCE_CEPH_POOL} ${GLANCE_CEPH_POOL_PG} ${GLANCE_CEPH_POOL_PGP}
    sudo ceph -c ${CEPH_CONF_FILE} auth get-or-create client.${GLANCE_CEPH_USER} \
        mon "allow r" \
        osd "allow class-read object_prefix rbd_children, allow rwx pool=${GLANCE_CEPH_POOL}" | \
        sudo tee ${CEPH_CONF_DIR}/ceph.client.${GLANCE_CEPH_USER}.keyring
    sudo chown ${STACK_USER}:$(id -g -n $whoami) ${CEPH_CONF_DIR}/ceph.client.${GLANCE_CEPH_USER}.keyring

    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=DEFAULT option=show_image_direct_url value=True"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=default_store value=rbd"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=stores value='file, http, rbd'"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=rbd_store_ceph_conf value=$CEPH_CONF_FILE"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=rbd_store_user value=$GLANCE_CEPH_USER"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=rbd_store_pool value=$GLANCE_CEPH_POOL"

    sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${GLANCE_CEPH_POOL} size ${CEPH_REPLICAS}
        if [[ $CEPH_REPLICAS -ne 1 ]]; then
            sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${GLANCE_CEPH_POOL} crush_ruleset ${RULE_ID}
        fi

    #copy glance keyring to compute only node
    sudo cp /etc/ceph/ceph.client.glance.keyring /tmp/ceph.client.glance.keyring
    sudo chown $STACK_USER:$STACK_USER /tmp/ceph.client.glance.keyring
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.client.glance.keyring dest=/etc/ceph/ceph.client.glance.keyring"
    sudo rm -f /tmp/ceph.client.glance.keyring
}

function configure_and_start_glance {
    _ceph_configure_glance
    echo 'check processes before glance-api stop'
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep glance-api"

    # restart glance
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl restart devstack@g-api"

    echo 'check processes after glance-api stop'
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep glance-api"
}

function _ceph_configure_nova {
    #setup ceph for nova, we don't reuse configure_ceph_nova - as we need to emulate case where cinder is not configured for ceph
    sudo ceph -c ${CEPH_CONF_FILE} osd pool create ${NOVA_CEPH_POOL} ${NOVA_CEPH_POOL_PG} ${NOVA_CEPH_POOL_PGP}
    NOVA_CONF=${NOVA_CPU_CONF:-/etc/nova/nova.conf}
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=rbd_user value=${CINDER_CEPH_USER}"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=rbd_secret_uuid value=${CINDER_CEPH_UUID}"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=inject_key value=false"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=inject_partition value=-2"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=disk_cachemodes value='network=writeback'"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_type value=rbd"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_rbd_pool value=${NOVA_CEPH_POOL}"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_rbd_ceph_conf value=${CEPH_CONF_FILE}"

    # Configure nova-compute to wait for network-vif-plugged events.
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=compute option=live_migration_wait_for_vif_plug value=True"

    sudo ceph -c ${CEPH_CONF_FILE} auth get-or-create client.${CINDER_CEPH_USER} \
    mon "allow r" \
    osd "allow class-read object_prefix rbd_children, allow rwx pool=${CINDER_CEPH_POOL}, allow rwx pool=${NOVA_CEPH_POOL},allow rwx pool=${GLANCE_CEPH_POOL}" | \
    sudo tee ${CEPH_CONF_DIR}/ceph.client.${CINDER_CEPH_USER}.keyring > /dev/null
    sudo chown ${STACK_USER}:$(id -g -n $whoami) ${CEPH_CONF_DIR}/ceph.client.${CINDER_CEPH_USER}.keyring

    #copy cinder keyring to compute only node
    sudo cp /etc/ceph/ceph.client.cinder.keyring /tmp/ceph.client.cinder.keyring
    sudo chown stack:stack /tmp/ceph.client.cinder.keyring
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.client.cinder.keyring dest=/etc/ceph/ceph.client.cinder.keyring"
    sudo rm -f /tmp/ceph.client.cinder.keyring

    sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${NOVA_CEPH_POOL} size ${CEPH_REPLICAS}
    if [[ $CEPH_REPLICAS -ne 1 ]]; then
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${NOVA_CEPH_POOL} crush_ruleset ${RULE_ID}
    fi
}

function configure_and_start_nova {
    _ceph_configure_nova
    #import secret to libvirt
    _populate_libvirt_secret
    echo 'check compute processes before restart'
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep compute"

    # restart nova-compute
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl restart devstack@n-cpu"

    # test that they are all running again
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep compute"

}

function _ceph_configure_cinder {
    sudo ceph -c ${CEPH_CONF_FILE} osd pool create ${CINDER_CEPH_POOL} ${CINDER_CEPH_POOL_PG} ${CINDER_CEPH_POOL_PGP}
    sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${CINDER_CEPH_POOL} size ${CEPH_REPLICAS}
    if [[ $CEPH_REPLICAS -ne 1 ]]; then
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${CINDER_CEPH_POOL} crush_ruleset ${RULE_ID}
    fi

    CINDER_CONF=${CINDER_CONF:-/etc/cinder/cinder.conf}
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=volume_backend_name value=ceph"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=volume_driver value=cinder.volume.drivers.rbd.RBDDriver"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_ceph_conf value=$CEPH_CONF_FILE"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_pool value=$CINDER_CEPH_POOL"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_user value=$CINDER_CEPH_USER"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_uuid value=$CINDER_CEPH_UUID"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_flatten_volume_from_snapshot value=False"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_max_clone_depth value=5"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=DEFAULT option=default_volume_type value=ceph"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=DEFAULT option=enabled_backends value=ceph"

}

function configure_and_start_cinder {
    _ceph_configure_cinder

    # restart cinder
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl restart devstack@c-vol"

    source $BASE/new/devstack/openrc

    export OS_USERNAME=admin
    export OS_PROJECT_NAME=admin
    lvm_type=$(cinder type-list | awk -F "|"  'NR==4{ print $2}')
    cinder type-delete $lvm_type
    openstack volume type create --os-volume-api-version 1 --property volume_backend_name="ceph" ceph
}

function _populate_libvirt_secret {
    cat > /tmp/secret.xml <<EOF
<secret ephemeral='no' private='no'>
   <uuid>${CINDER_CEPH_UUID}</uuid>
   <usage type='ceph'>
     <name>client.${CINDER_CEPH_USER} secret</name>
   </usage>
</secret>
EOF

    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/secret.xml dest=/tmp/secret.xml"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "virsh secret-define --file /tmp/secret.xml"
    local secret=$(sudo ceph -c ${CEPH_CONF_FILE} auth get-key client.${CINDER_CEPH_USER})
    # TODO(tdurakov): remove this escaping as https://github.com/ansible/ansible/issues/13862 fixed
    secret=${secret//=/'\='}
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "virsh secret-set-value --secret ${CINDER_CEPH_UUID} --base64 $secret"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m file -a "path=/tmp/secret.xml state=absent"

}
