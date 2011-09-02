#!/usr/bin/env bash
DIR=`pwd`
CMD=$1
if [ "$CMD" = "branch" ]; then
    SOURCE_BRANCH=${2:-lp:nova}
    DIRNAME=${3:-nova}
else
    DIRNAME=${2:-nova}
fi

NOVA_DIR=$DIR/$DIRNAME

if [ ! -n "$HOST_IP" ]; then
    # NOTE(vish): This will just get the first ip in the list, so if you
    #             have more than one eth device set up, this will fail, and
    #             you should explicitly set HOST_IP in your environment
    HOST_IP=`LC_ALL=C ifconfig  | grep -m 1 'inet addr:'| cut -d: -f2 | awk '{print $1}'`
fi

USE_MYSQL=${USE_MYSQL:-1}
INTERFACE=${INTERFACE:-eth0}
FLOATING_RANGE=${FLOATING_RANGE:-10.6.0.0/27}
FIXED_RANGE=${FIXED_RANGE:-10.0.0.0/24}
MYSQL_PASS=${MYSQL_PASS:-nova}
TEST=${TEST:-0}
USE_LDAP=${USE_LDAP:-0}
# Use OpenDJ instead of OpenLDAP when using LDAP
USE_OPENDJ=${USE_OPENDJ:-0}
# Use IPv6
USE_IPV6=${USE_IPV6:-0}
LIBVIRT_TYPE=${LIBVIRT_TYPE:-qemu}
NET_MAN=${NET_MAN:-VlanManager}
# NOTE(vish): If you are using FlatDHCP on multiple hosts, set the interface
#             below but make sure that the interface doesn't already have an
#             ip or you risk breaking things.
# FLAT_INTERFACE=eth0

if [ "$USE_MYSQL" == 1 ]; then
    SQL_CONN=mysql://root:$MYSQL_PASS@localhost/nova
else
    SQL_CONN=sqlite:///$NOVA_DIR/nova.sqlite
fi

if [ "$USE_LDAP" == 1 ]; then
    AUTH=ldapdriver.LdapDriver
else
    AUTH=dbdriver.DbDriver
fi

if [ "$CMD" == "branch" ]; then
    sudo apt-get install -y bzr
    if [ ! -e "$DIR/.bzr" ]; then
        bzr init-repo $DIR
    fi
    rm -rf $NOVA_DIR
    bzr branch $SOURCE_BRANCH $NOVA_DIR
    cd $NOVA_DIR
    mkdir -p $NOVA_DIR/instances
    mkdir -p $NOVA_DIR/networks
    exit
fi

# You should only have to run this once
if [ "$CMD" == "install" ]; then
    sudo apt-get install -y python-software-properties
    sudo add-apt-repository ppa:nova-core/trunk
    sudo apt-get update
    sudo apt-get install -y dnsmasq-base kpartx kvm gawk iptables ebtables
    sudo apt-get install -y user-mode-linux kvm libvirt-bin
    sudo apt-get install -y screen euca2ools vlan curl rabbitmq-server
    sudo apt-get install -y lvm2 iscsitarget open-iscsi
    sudo apt-get install -y socat unzip
    echo "ISCSITARGET_ENABLE=true" | sudo tee /etc/default/iscsitarget
    sudo /etc/init.d/iscsitarget restart
    sudo modprobe kvm
    sudo /etc/init.d/libvirt-bin restart
    sudo modprobe nbd
    sudo apt-get install -y python-mox python-ipy python-paste
    sudo apt-get install -y python-migrate python-gflags python-greenlet
    sudo apt-get install -y python-libvirt python-libxml2 python-routes
    sudo apt-get install -y python-netaddr python-pastedeploy python-eventlet
    sudo apt-get install -y python-novaclient python-glance python-cheetah
    sudo apt-get install -y python-carrot python-tempita python-sqlalchemy
    sudo apt-get install -y python-suds python-kombu


    if [ "$USE_IPV6" == 1 ]; then
        sudo apt-get install -y radvd
        sudo bash -c "echo 1 > /proc/sys/net/ipv6/conf/all/forwarding"
        sudo bash -c "echo 0 > /proc/sys/net/ipv6/conf/all/accept_ra"
    fi

    if [ "$USE_MYSQL" == 1 ]; then
        cat <<MYSQL_PRESEED | debconf-set-selections
mysql-server-5.1 mysql-server/root_password password $MYSQL_PASS
mysql-server-5.1 mysql-server/root_password_again password $MYSQL_PASS
mysql-server-5.1 mysql-server/start_on_boot boolean true
MYSQL_PRESEED
        apt-get install -y mysql-server python-mysqldb
    fi
    mkdir -p $DIR/images
    wget -c http://images.ansolabs.com/tty.tgz
    tar -C $DIR/images -zxf tty.tgz
    exit
fi

NL=`echo -ne '\015'`

function screen_it {
    screen -S nova -X screen -t $1
    screen -S nova -p $1 -X stuff "$2$NL"
}

if [ "$CMD" == "run" ] || [ "$CMD" == "run_detached" ]; then

  cat >$NOVA_DIR/bin/nova.conf << NOVA_CONF_EOF
--verbose
--nodaemon
--dhcpbridge_flagfile=$NOVA_DIR/bin/nova.conf
--network_manager=nova.network.manager.$NET_MAN
--my_ip=$HOST_IP
--public_interface=$INTERFACE
--vlan_interface=$INTERFACE
--sql_connection=$SQL_CONN
--auth_driver=nova.auth.$AUTH
--libvirt_type=$LIBVIRT_TYPE
NOVA_CONF_EOF

    if [ -n "$FLAT_INTERFACE" ]; then
        echo "--flat_interface=$FLAT_INTERFACE" >>$NOVA_DIR/bin/nova.conf
    fi

    if [ "$USE_IPV6" == 1 ]; then
        echo "--use_ipv6" >>$NOVA_DIR/bin/nova.conf
    fi

    killall dnsmasq
    if [ "$USE_IPV6" == 1 ]; then
       killall radvd
    fi
    screen -d -m -S nova -t nova
    sleep 1
    if [ "$USE_MYSQL" == 1 ]; then
        mysql -p$MYSQL_PASS -e 'DROP DATABASE nova;'
        mysql -p$MYSQL_PASS -e 'CREATE DATABASE nova;'
    else
        rm $NOVA_DIR/nova.sqlite
    fi
    if [ "$USE_LDAP" == 1 ]; then
        if [ "$USE_OPENDJ" == 1 ]; then
            echo '--ldap_user_dn=cn=Directory Manager' >> \
                /etc/nova/nova-manage.conf
            sudo $NOVA_DIR/nova/auth/opendj.sh
        else
            sudo $NOVA_DIR/nova/auth/slap.sh
        fi
    fi
    rm -rf $NOVA_DIR/instances
    mkdir -p $NOVA_DIR/instances
    rm -rf $NOVA_DIR/networks
    mkdir -p $NOVA_DIR/networks
    if [ "$TEST" == 1 ]; then
        cd $NOVA_DIR
        python $NOVA_DIR/run_tests.py
        cd $DIR
    fi

    # create the database
    $NOVA_DIR/bin/nova-manage db sync
    # create an admin user called 'admin'
    $NOVA_DIR/bin/nova-manage user admin admin admin admin
    # create a project called 'admin' with project manager of 'admin'
    $NOVA_DIR/bin/nova-manage project create admin admin
    # create a small network
    $NOVA_DIR/bin/nova-manage network create $FIXED_RANGE 1 32

    # create some floating ips
    $NOVA_DIR/bin/nova-manage floating create `hostname` $FLOATING_RANGE

    if [ ! -d "$NOVA_DIR/images" ]; then
        if [ ! -d "$DIR/converted-images" ]; then
            # convert old images
            mkdir $DIR/converted-images
            ln -s $DIR/converted-images $NOVA_DIR/images
            $NOVA_DIR/bin/nova-manage image convert $DIR/images
        else
            ln -s $DIR/converted-images $NOVA_DIR/images
        fi

    fi


    # nova api crashes if we start it with a regular screen command,
    # so send the start command by forcing text into the window.
    screen_it api "$NOVA_DIR/bin/nova-api"
    screen_it objectstore "$NOVA_DIR/bin/nova-objectstore"
    screen_it compute "$NOVA_DIR/bin/nova-compute"
    screen_it network "$NOVA_DIR/bin/nova-network"
    screen_it scheduler "$NOVA_DIR/bin/nova-scheduler"
    screen_it volume "$NOVA_DIR/bin/nova-volume"
    screen_it ajax_console_proxy "$NOVA_DIR/bin/nova-ajax-console-proxy"
    sleep 2
    # export environment variables for project 'admin' and user 'admin'
    $NOVA_DIR/bin/nova-manage project zipfile admin admin $NOVA_DIR/nova.zip
    unzip -o $NOVA_DIR/nova.zip -d $NOVA_DIR/

    screen_it test "export PATH=$NOVA_DIR/bin:$PATH;. $NOVA_DIR/novarc"
    if [ "$CMD" != "run_detached" ]; then
      screen -S nova -x
    fi
fi

if [ "$CMD" == "run" ] || [ "$CMD" == "terminate" ]; then
    # shutdown instances
    . $NOVA_DIR/novarc; euca-describe-instances | grep i- | cut -f2 | xargs euca-terminate-instances
    sleep 2
    # delete volumes
    . $NOVA_DIR/novarc; euca-describe-volumes | grep vol- | cut -f2 | xargs -n1 euca-delete-volume
    sleep 2
fi

if [ "$CMD" == "run" ] || [ "$CMD" == "clean" ]; then
    screen -S nova -X quit
    rm *.pid*
fi

if [ "$CMD" == "scrub" ]; then
    $NOVA_DIR/tools/clean-vlans
    if [ "$LIBVIRT_TYPE" == "uml" ]; then
        virsh -c uml:///system list | grep i- | awk '{print \$1}' | xargs -n1 virsh -c uml:///system destroy
    else
        virsh list | grep i- | awk '{print \$1}' | xargs -n1 virsh destroy
    fi
fi
