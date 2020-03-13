#!/bin/bash

function prepare_ceph {
    git clone https://opendev.org/openstack/devstack-plugin-ceph /tmp/devstack-plugin-ceph
    source /tmp/devstack-plugin-ceph/devstack/settings
    source /tmp/devstack-plugin-ceph/devstack/lib/ceph
    install_ceph
    configure_ceph
    #install ceph-common package and additional python3 ceph libraries on compute nodes
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m raw -a "executable=/bin/bash
    USE_PYTHON3=${USE_PYTHON3:-True}
    source $BASE/new/devstack/functions
    source $BASE/new/devstack/functions-common
    git clone https://opendev.org/openstack/devstack-plugin-ceph /tmp/devstack-plugin-ceph
    source /tmp/devstack-plugin-ceph/devstack/lib/ceph
    install_ceph_remote
    "

    #copy ceph admin keyring to compute nodes
    sudo cp /etc/ceph/ceph.client.admin.keyring /tmp/ceph.client.admin.keyring
    sudo chown ${STACK_USER}:${STACK_USER} /tmp/ceph.client.admin.keyring
    sudo chmod 644 /tmp/ceph.client.admin.keyring
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.client.admin.keyring dest=/etc/ceph/ceph.client.admin.keyring owner=ceph group=ceph"
    sudo rm -f /tmp/ceph.client.admin.keyring
    #copy ceph.conf to compute nodes
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/etc/ceph/ceph.conf dest=/etc/ceph/ceph.conf owner=root group=root"

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

    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=DEFAULT option=show_image_direct_url value=True"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=default_store value=rbd"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=stores value='file, http, rbd'"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=rbd_store_ceph_conf value=$CEPH_CONF_FILE"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=rbd_store_user value=$GLANCE_CEPH_USER"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${GLANCE_API_CONF} section=glance_store option=rbd_store_pool value=$GLANCE_CEPH_POOL"

    sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${GLANCE_CEPH_POOL} size ${CEPH_REPLICAS}
        if [[ $CEPH_REPLICAS -ne 1 ]]; then
            sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${GLANCE_CEPH_POOL} crush_ruleset ${RULE_ID}
        fi

    #copy glance keyring to compute only node
    sudo cp /etc/ceph/ceph.client.glance.keyring /tmp/ceph.client.glance.keyring
    sudo chown $STACK_USER:$STACK_USER /tmp/ceph.client.glance.keyring
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.client.glance.keyring dest=/etc/ceph/ceph.client.glance.keyring"
    sudo rm -f /tmp/ceph.client.glance.keyring
}

function configure_and_start_glance {
    _ceph_configure_glance
    echo 'check processes before glance-api stop'
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep glance-api"

    # restart glance
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl restart devstack@g-api"

    echo 'check processes after glance-api stop'
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep glance-api"
}

function _ceph_configure_nova {
    #setup ceph for nova, we don't reuse configure_ceph_nova - as we need to emulate case where cinder is not configured for ceph
    sudo ceph -c ${CEPH_CONF_FILE} osd pool create ${NOVA_CEPH_POOL} ${NOVA_CEPH_POOL_PG} ${NOVA_CEPH_POOL_PGP}
    NOVA_CONF=${NOVA_CPU_CONF:-/etc/nova/nova.conf}
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=rbd_user value=${CINDER_CEPH_USER}"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=rbd_secret_uuid value=${CINDER_CEPH_UUID}"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=inject_key value=false"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=inject_partition value=-2"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=disk_cachemodes value='network=writeback'"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_type value=rbd"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_rbd_pool value=${NOVA_CEPH_POOL}"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_rbd_ceph_conf value=${CEPH_CONF_FILE}"

    sudo ceph -c ${CEPH_CONF_FILE} auth get-or-create client.${CINDER_CEPH_USER} \
    mon "allow r" \
    osd "allow class-read object_prefix rbd_children, allow rwx pool=${CINDER_CEPH_POOL}, allow rwx pool=${NOVA_CEPH_POOL},allow rwx pool=${GLANCE_CEPH_POOL}" | \
    sudo tee ${CEPH_CONF_DIR}/ceph.client.${CINDER_CEPH_USER}.keyring > /dev/null
    sudo chown ${STACK_USER}:$(id -g -n $whoami) ${CEPH_CONF_DIR}/ceph.client.${CINDER_CEPH_USER}.keyring

    #copy cinder keyring to compute only node
    sudo cp /etc/ceph/ceph.client.cinder.keyring /tmp/ceph.client.cinder.keyring
    sudo chown stack:stack /tmp/ceph.client.cinder.keyring
    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.client.cinder.keyring dest=/etc/ceph/ceph.client.cinder.keyring"
    sudo rm -f /tmp/ceph.client.cinder.keyring

    sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${NOVA_CEPH_POOL} size ${CEPH_REPLICAS}
    if [[ $CEPH_REPLICAS -ne 1 ]]; then
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${NOVA_CEPH_POOL} crush_ruleset ${RULE_ID}
    fi
}

function _wait_for_nova_compute_service_state {
    source $BASE/new/devstack/openrc admin admin
    local status=$1
    local attempt=1
    local max_attempts=24
    local attempt_sleep=5
    local computes_count=$(openstack compute service list | grep -c nova-compute)
    local computes_ready=$(openstack compute service list | grep nova-compute | grep $status | wc -l)

    echo "Waiting for $computes_count computes to report as $status"
    while [ "$computes_ready" -ne "$computes_count" ]; do
        if [ "$attempt" -eq "$max_attempts" ]; then
            echo "Failed waiting for computes to report as ${status}, ${computes_ready}/${computes_count} ${status} after ${max_attempts} attempts"
            exit 4
        fi
        echo "Waiting ${attempt_sleep} seconds for ${computes_count} computes to report as ${status}, ${computes_ready}/${computes_count} ${status} after ${attempt}/${max_attempts} attempts"
        sleep $attempt_sleep
        attempt=$((attempt+1))
        computes_ready=$(openstack compute service list | grep nova-compute | grep $status | wc -l)
    done
    echo "All computes are now reporting as ${status} after ${attempt} attempts"
}

function configure_and_start_nova {

    echo "Checking all n-cpu services"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "pgrep -u stack -a nova-compute"

    # stop nova-compute
    echo "Stopping all n-cpu services"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl stop devstack@n-cpu"

    # Wait for the service to be marked as down
    _wait_for_nova_compute_service_state "down"

    _ceph_configure_nova

    #import secret to libvirt
    _populate_libvirt_secret

    # start nova-compute
    echo "Starting all n-cpu services"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl start devstack@n-cpu"

    echo "Checking all n-cpu services"
    # test that they are all running again
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "pgrep -u stack -a nova-compute"

    # Wait for the service to be marked as up
    _wait_for_nova_compute_service_state "up"
}

function _ceph_configure_cinder {
    sudo ceph -c ${CEPH_CONF_FILE} osd pool create ${CINDER_CEPH_POOL} ${CINDER_CEPH_POOL_PG} ${CINDER_CEPH_POOL_PGP}
    sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${CINDER_CEPH_POOL} size ${CEPH_REPLICAS}
    if [[ $CEPH_REPLICAS -ne 1 ]]; then
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set ${CINDER_CEPH_POOL} crush_ruleset ${RULE_ID}
    fi

    CINDER_CONF=${CINDER_CONF:-/etc/cinder/cinder.conf}
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=volume_backend_name value=ceph"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=volume_driver value=cinder.volume.drivers.rbd.RBDDriver"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_ceph_conf value=$CEPH_CONF_FILE"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_pool value=$CINDER_CEPH_POOL"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_user value=$CINDER_CEPH_USER"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_uuid value=$CINDER_CEPH_UUID"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_flatten_volume_from_snapshot value=False"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=ceph option=rbd_max_clone_depth value=5"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=DEFAULT option=default_volume_type value=ceph"
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=DEFAULT option=enabled_backends value=ceph"

}

function configure_and_start_cinder {
    _ceph_configure_cinder

    # restart cinder
    $ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl restart devstack@c-vol"

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

    $ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/secret.xml dest=/tmp/secret.xml"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "virsh secret-define --file /tmp/secret.xml"
    local secret=$(sudo ceph -c ${CEPH_CONF_FILE} auth get-key client.${CINDER_CEPH_USER})
    # TODO(tdurakov): remove this escaping as https://github.com/ansible/ansible/issues/13862 fixed
    secret=${secret//=/'\='}
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "virsh secret-set-value --secret ${CINDER_CEPH_UUID} --base64 $secret"
    $ANSIBLE all --become -f 5 -i "$WORKSPACE/inventory" -m file -a "path=/tmp/secret.xml state=absent"

}
