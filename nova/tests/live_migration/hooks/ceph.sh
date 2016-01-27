#!/bin/bash

CEPH_REPLICAS=2

function setup_ceph_cluster {
    install_ceph_full
    configure_ceph_local

    echo "copy ceph.conf and admin keyring to compute only nodes"
    ls -la /etc/ceph
    sudo cp /etc/ceph/ceph.conf /tmp/ceph.conf
    sudo chown ${STACK_USER}:${STACK_USER} /tmp/ceph.conf
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.conf dest=/etc/ceph/ceph.conf owner=root group=root"
    sudo rm -f /tmp/ceph.conf
    sudo cp /etc/ceph/ceph.client.admin.keyring /tmp/ceph.client.admin.keyring
    sudo chown ${STACK_USER}:${STACK_USER} /tmp/ceph.client.admin.keyring
    sudo chmod 644 /tmp/ceph.client.admin.keyring
    ls -la /tmp
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m copy -a "src=/tmp/ceph.client.admin.keyring dest=/etc/ceph/ceph.client.admin.keyring owner=root group=root"
    sudo rm -f /tmp/ceph.client.admin.keyring
    echo "check result of copying files"
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ls -la /etc/ceph"


    echo "start ceph-mon"
    sudo initctl emit ceph-mon id=$(hostname)
    echo "start ceph-osd"
    sudo start ceph-osd id=${OSD_ID}
    echo "check ceph-osd before second node addition"
    wait_for_ceph_up

    configure_ceph_remote

    echo "check ceph-osd tree"
    wait_for_ceph_up
}

function install_ceph_full {
    if uses_debs; then
        $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m apt \
                -a "name=ceph state=present"
    elif is_fedora; then
        $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m yum \
                -a "name=ceph state=present"
    fi
}

function configure_ceph_local {
    sudo mkdir -p ${CEPH_DATA_DIR}/{bootstrap-mds,bootstrap-osd,mds,mon,osd,tmp}

    # create ceph monitor initial key and directory
    sudo ceph-authtool /var/lib/ceph/tmp/keyring.mon.$(hostname) \
        --create-keyring --name=mon. --add-key=$(ceph-authtool --gen-print-key) \
        --cap mon 'allow *'
    sudo mkdir /var/lib/ceph/mon/ceph-$(hostname)

    # create a default ceph configuration file
    sudo tee ${CEPH_CONF_FILE} > /dev/null <<EOF
[global]
fsid = ${CEPH_FSID}
mon_initial_members = $(hostname)
mon_host = ${SERVICE_HOST}
auth_cluster_required = cephx
auth_service_required = cephx
auth_client_required = cephx
filestore_xattr_use_omap = true
osd crush chooseleaf type = 0
osd journal size = 100
EOF

    # bootstrap the ceph monitor
    sudo ceph-mon -c ${CEPH_CONF_FILE} --mkfs -i $(hostname) \
        --keyring /var/lib/ceph/tmp/keyring.mon.$(hostname)

    if is_ubuntu; then
        sudo touch /var/lib/ceph/mon/ceph-$(hostname)/upstart
        sudo initctl emit ceph-mon id=$(hostname)
    else
        sudo touch /var/lib/ceph/mon/ceph-$(hostname)/sysvinit
        sudo service ceph start mon.$(hostname)
    fi

    # wait for the admin key to come up otherwise we will not be able to do the actions below
    until [ -f ${CEPH_CONF_DIR}/ceph.client.admin.keyring ]; do
        echo_summary "Waiting for the Ceph admin key to be ready..."

        count=$(($count + 1))
        if [ $count -eq 3 ]; then
            die $LINENO "Maximum of 3 retries reached"
        fi
        sleep 5
    done

    # pools data and metadata were removed in the Giant release so depending on the version we apply different commands
    ceph_version=$(get_ceph_version)
    # change pool replica size according to the CEPH_REPLICAS set by the user
    if [[ ${ceph_version%%.*} -eq 0 ]] && [[ ${ceph_version##*.} -lt 87 ]]; then
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set rbd size ${CEPH_REPLICAS}
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set data size ${CEPH_REPLICAS}
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set metadata size ${CEPH_REPLICAS}
    else
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set rbd size ${CEPH_REPLICAS}
    fi

    # create a simple rule to take OSDs instead of host with CRUSH
    # then apply this rules to the default pool
    if [[ $CEPH_REPLICAS -ne 1 ]]; then
        sudo ceph -c ${CEPH_CONF_FILE} osd crush rule create-simple devstack default osd
        RULE_ID=$(sudo ceph -c ${CEPH_CONF_FILE} osd crush rule dump devstack | awk '/rule_id/ {print $3}' | cut -d ',' -f1)
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set rbd crush_ruleset ${RULE_ID}
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set data crush_ruleset ${RULE_ID}
        sudo ceph -c ${CEPH_CONF_FILE} osd pool set metadata crush_ruleset ${RULE_ID}
    fi

    OSD_ID=$(sudo ceph -c ${CEPH_CONF_FILE} osd create)
    sudo mkdir -p ${CEPH_DATA_DIR}/osd/ceph-${OSD_ID}
    sudo ceph-osd -c ${CEPH_CONF_FILE} -i ${OSD_ID} --mkfs
    sudo ceph auth get-or-create osd.${OSD_ID} \
        mon 'allow profile osd ' osd 'allow *' | \
        sudo tee /var/lib/ceph/osd/ceph-${OSD_ID}/keyring

    # ceph's init script is parsing ${CEPH_DATA_DIR}/osd/ceph-${OSD_ID}/ and looking for a file
    # 'upstart' or 'sysinitv', thanks to these 'touches' we are able to control OSDs daemons
    # from the init script.
    if is_ubuntu; then
        sudo touch /var/lib/ceph/osd/ceph-${OSD_ID}/upstart
    else
        sudo touch ${CEPH_DATA_DIR}/osd/ceph-${OSD_ID}/sysvinit
    fi

}

function configure_ceph_remote {
    echo "boot osd on compute only node"
    $ANSIBLE subnodes --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a 'CEPH_CONF_FILE\=/etc/ceph/ceph.conf
    CEPH_DATA_DIR\=/var/lib/ceph/
    OSD_ID\=$(sudo ceph -c ${CEPH_CONF_FILE} osd create)
    sudo mkdir -p ${CEPH_DATA_DIR}/osd/ceph-${OSD_ID}
    sudo ceph-osd -c ${CEPH_CONF_FILE} -i ${OSD_ID} --mkfs
    sudo ceph -c ${CEPH_CONF_FILE} auth get-or-create osd.${OSD_ID} \
    mon "allow profile osd" osd "allow *" | \
    sudo tee ${CEPH_DATA_DIR}/osd/ceph-${OSD_ID}/keyring
    sudo touch ${CEPH_DATA_DIR}/osd/ceph-${OSD_ID}/upstart
    sudo start ceph-osd id\=${OSD_ID}
    '
}

function wait_for_ceph_up {
    for i in $(seq 1 3); do
        ceph_osd_stat=$(sudo ceph osd stat)
        total_osd_amount=$(sudo ceph osd stat | awk -F ":"  '{ print $2}' | sed 's/[^0-9]*//g')
        up_osd_amout=$(sudo ceph osd stat | awk -F ":"  '{ print $3}' | awk -F "," '{print $1}'| sed 's/[^0-9]*//g')
        in_cluster_osd_amout=$(sudo ceph osd stat | awk -F ":"  '{ print $3}' | awk -F "," '{print $2}'| sed 's/[^0-9]*//g')
        if [ "$total_osd_amount" -eq "$up_osd_amout" -a "$up_osd_amout" -eq "$in_cluster_osd_amout" ]
        then
          echo "All OSDs are up and ready"
          return
        fi
        sleep 3
    done
    die $LINENO "Maximum of 3 retries reached. Failed to start osds properly"
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

    #stop g-api
    stop 'primary' 'g-api'

    echo 'check processes after glance-api stop'
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep glance-api"

    # restart glance
    sudo -H -u $STACK_USER bash -c "/tmp/start_process.sh g-api '/usr/local/bin/glance-api --config-file=/etc/glance/glance-api.conf'"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep glance-api"
}

function _ceph_configure_nova {
    #setup ceph for nova, we don't reuse configure_ceph_nova - as we need to emulate case where cinder is not configured for ceph
    sudo ceph -c ${CEPH_CONF_FILE} osd pool create ${NOVA_CEPH_POOL} ${NOVA_CEPH_POOL_PG} ${NOVA_CEPH_POOL_PGP}
    NOVA_CONF=${NOVA_CONF:-/etc/nova/nova.conf}
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=rbd_user value=${CINDER_CEPH_USER}"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=rbd_secret_uuid value=${CINDER_CEPH_UUID}"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=inject_key value=false"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=inject_partition value=-2"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=disk_cachemodes value='network=writeback'"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_type value=rbd"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_rbd_pool value=${NOVA_CEPH_POOL}"
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=${NOVA_CONF} section=libvirt option=images_rbd_ceph_conf value=${CEPH_CONF_FILE}"

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

    #stop nova-compute
    stop 'all' 'n-cpu'

    echo 'check processes after compute stop'
    $ANSIBLE all --sudo -f 5 -i "$WORKSPACE/inventory" -m shell -a "ps aux | grep compute"

    # restart  local nova-compute
    sudo -H -u $STACK_USER bash -c "/tmp/start_process.sh n-cpu '/usr/local/bin/nova-compute --config-file /etc/nova/nova.conf' libvirtd"

    # restart remote nova-compute
    for SUBNODE in $SUBNODES ; do
        ssh $SUBNODE "sudo -H -u $STACK_USER bash -c '/tmp/start_process.sh n-cpu \"/usr/local/bin/nova-compute --config-file /etc/nova/nova.conf\" libvirtd'"
    done
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
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=DEFAULT option=glance_api_version value=2"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=DEFAULT option=default_volume_type value=ceph"
    $ANSIBLE primary --sudo -f 5 -i "$WORKSPACE/inventory" -m ini_file -a  "dest=$CINDER_CONF section=DEFAULT option=enabled_backends value=ceph"

}

function configure_and_start_cinder {
    _ceph_configure_cinder
    stop 'primary' 'c-vol'

    sudo -H -u $STACK_USER bash -c "/tmp/start_process.sh c-vol '/usr/local/bin/cinder-volume --config-file /etc/cinder/cinder.conf'"
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
