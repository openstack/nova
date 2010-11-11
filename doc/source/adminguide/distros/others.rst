Installation (Other distros like Debian, Fedora or CentOS )
===========================================================

Feel free to add additional notes for additional distributions.

Nova installation on CentOS 5.5
-------------------------------

These are notes for installing OpenStack Compute on CentOS 5.5 and will be updated but are NOT final. Please test for accuracy and edit as you see fit.

The principle botleneck for running nova on centos in python 2.6. Nova is written in python 2.6 and CentOS 5.5. comes with python 2.4. We can not update python system wide as some core utilities (like yum) is dependent on python 2.4. Also very few python 2.6 modules are available in centos/epel repos.

Pre-reqs
--------

Add euca2ools and EPEL repo first.::

    cat >/etc/yum.repos.d/euca2ools.repo << EUCA_REPO_CONF_EOF
    [eucalyptus]
    name=euca2ools
    baseurl=http://www.eucalyptussoftware.com/downloads/repo/euca2ools/1.3.1/yum/centos/
    enabled=1
    gpgcheck=0

    EUCA_REPO_CONF_EOF

::

    rpm -Uvh 'http://download.fedora.redhat.com/pub/epel/5/i386/epel-release-5-4.noarch.rpm'

Now install python2.6, kvm and few other libraries through yum::

    yum -y  install dnsmasq  vblade kpartx kvm gawk iptables ebtables  bzr screen euca2ools  curl rabbitmq-server gcc gcc-c++ autoconf automake swig  openldap openldap-servers nginx  python26 python26-devel python26-distribute git openssl-devel  python26-tools mysql-server qemu kmod-kvm libxml2 libxslt libxslt-devel mysql-devel

Then download the latest aoetools and then build(and install) it, check for the latest version on sourceforge, exact url will change if theres a new release::

    wget -c http://sourceforge.net/projects/aoetools/files/aoetools/32/aoetools-32.tar.gz/download
    tar -zxvf aoetools-32.tar.gz
    cd aoetools-32
    make
    make install

Add the udev rules for aoetools::

    cat > /etc/udev/rules.d/60-aoe.rules << AOE_RULES_EOF
    SUBSYSTEM=="aoe", KERNEL=="discover",    NAME="etherd/%k", GROUP="disk", MODE="0220"
    SUBSYSTEM=="aoe", KERNEL=="err",    NAME="etherd/%k", GROUP="disk", MODE="0440"
    SUBSYSTEM=="aoe", KERNEL=="interfaces",    NAME="etherd/%k", GROUP="disk", MODE="0220"
    SUBSYSTEM=="aoe", KERNEL=="revalidate",    NAME="etherd/%k", GROUP="disk", MODE="0220"
    # aoe block devices
    KERNEL=="etherd*",       NAME="%k", GROUP="disk"
    AOE_RULES_EOF

Load the kernel modules::

    modprobe aoe

::

    modprobe kvm

Now, install the python modules using easy_install-2.6, this ensures the installation are done against python 2.6


easy_install-2.6     twisted sqlalchemy mox greenlet carrot daemon eventlet tornado IPy  routes  lxml MySQL-python
python-gflags need to be downloaded and installed manually, use these commands (check the exact url for newer releases ):

::

    wget -c "http://python-gflags.googlecode.com/files/python-gflags-1.4.tar.gz"
    tar -zxvf python-gflags-1.4.tar.gz
    cd python-gflags-1.4
    python2.6 setup.py install
    cd ..

Same for python2.6-libxml2 module, notice the --with-python and --prefix flags. --with-python ensures we are building it against python2.6 (otherwise it will build against python2.4, which is default)::

    wget -c "ftp://xmlsoft.org/libxml2/libxml2-2.7.3.tar.gz"
    tar -zxvf libxml2-2.7.3.tar.gz
    cd libxml2-2.7.3
    ./configure --with-python=/usr/bin/python26 --prefix=/usr
    make all
    make install
    cd python
    python2.6 setup.py install
    cd ..

Once you've done this, continue at Step 3 here: :doc:`../single.node.install`
