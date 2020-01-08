================================================
Testing NUMA related hardware setup with libvirt
================================================

This page describes how to test the libvirt driver's handling of the NUMA
placement, large page allocation and CPU pinning features. It relies on setting
up a virtual machine as the test environment and requires support for nested
virtualization since plain QEMU is not sufficiently functional. The virtual
machine will itself be given NUMA topology, so it can then act as a virtual
"host" for testing purposes.

------------------------------------------
Provisioning a virtual machine for testing
------------------------------------------

The entire test process will take place inside a large virtual machine running
Fedora 24. The instructions should work for any other Linux distribution which
includes libvirt >= 1.2.9 and QEMU >= 2.1.2

The tests will require support for nested KVM, which is not enabled by default
on hypervisor hosts. It must be explicitly turned on in the host when loading
the kvm-intel/kvm-amd kernel modules.

On Intel hosts verify it with

.. code-block:: bash

 # cat /sys/module/kvm_intel/parameters/nested
 N

 # rmmod kvm-intel
 # echo "options kvm-intel nested=y" > /etc/modprobe.d/dist.conf
 # modprobe kvm-intel

 # cat /sys/module/kvm_intel/parameters/nested
 Y

While on AMD hosts verify it with

.. code-block:: bash

 # cat /sys/module/kvm_amd/parameters/nested
 0

 # rmmod kvm-amd
 # echo "options kvm-amd nested=1" > /etc/modprobe.d/dist.conf
 # modprobe kvm-amd

 # cat /sys/module/kvm_amd/parameters/nested
 1

The virt-install command below shows how to provision a basic Fedora 24 x86_64
guest with 8 virtual CPUs, 8 GB of RAM and 20 GB of disk space:

.. code-block:: bash

 # cd /var/lib/libvirt/images
 # wget https://download.fedoraproject.org/pub/fedora/linux/releases/29/Server/x86_64/iso/Fedora-Server-netinst-x86_64-29-1.2.iso

 # virt-install \
    --name f29x86_64 \
    --ram 8000 \
    --vcpus 8 \
    --file /var/lib/libvirt/images/f29x86_64.img \
    --file-size 20
    --cdrom /var/lib/libvirt/images/Fedora-Server-netinst-x86_64-24-1.2.iso \
    --os-variant fedora23

When the virt-viewer application displays the installer, follow the defaults
for the installation with a couple of exceptions:

* The automatic disk partition setup can be optionally tweaked to reduce the
  swap space allocated. No more than 500MB is required, free'ing up an extra
  1.5 GB for the root disk

* Select "Minimal install" when asked for the installation type since a desktop
  environment is not required

* When creating a user account be sure to select the option "Make this user
  administrator" so it gets 'sudo' rights

Once the installation process has completed, the virtual machine will reboot
into the final operating system. It is now ready to deploy an OpenStack
development environment.

---------------------------------
Setting up a devstack environment
---------------------------------

For later ease of use, copy your SSH public key into the virtual machine:

.. code-block:: bash

  # ssh-copy-id  <IP of VM>

Now login to the virtual machine:

.. code-block:: bash

  # ssh <IP of VM>

The Fedora minimal install does not contain git. Install git and clone the
devstack repo:

.. code-block:: bash

  $ sudo dnf install git
  $ git clone https://opendev.org/openstack/devstack
  $ cd devstack

At this point a fairly standard devstack setup can be done with one exception:
we should enable the ``NUMATopologyFilter`` filter, which we will use later.
For example:

.. code-block:: bash

  $ cat >>local.conf <<EOF
  [[local|localrc]]
  DATA_DIR=$DEST/data
  SERVICE_DIR=$DEST/status

  LOGFILE=$DATA_DIR/logs/stack.log
  VERBOSE=True

  disable_service n-net
  enable_service neutron q-svc q-dhcp q-l3 q-meta q-agt

  MYSQL_PASSWORD=123456
  DATABASE_PASSWORD=123456
  SERVICE_TOKEN=123456
  SERVICE_PASSWORD=123456
  ADMIN_PASSWORD=123456
  RABBIT_PASSWORD=123456

  [[post-config|$NOVA_CONF]]
  [filter_scheduler]
  enabled_filters=ComputeFilter,AvailabilityZoneFilter,ComputeCapabilitiesFilter,ImagePropertiesFilter,PciPassthroughFilter,NUMATopologyFilter
  EOF
  $ FORCE=yes ./stack.sh

Unfortunately while devstack starts various system services and changes various
system settings it doesn't make the changes persistent. Fix that now to avoid
later surprises after reboots:

.. code-block:: bash

  $ sudo systemctl enable mariadb.service
  $ sudo systemctl enable rabbitmq-server.service
  $ sudo systemctl enable httpd.service

  $ sudo vi /etc/sysconfig/selinux
  SELINUX=permissive

----------------------------
Testing basis non-NUMA usage
----------------------------

First to confirm we've not done anything unusual to the traditional operation
of nova libvirt guests boot a tiny instance:

.. code-block:: bash

  $ . openrc admin
  $ openstack server create --image cirros-0.4.0-x86_64-disk --flavor m1.tiny \
      cirros1

The host will be reporting NUMA topology, but there should only be a single
NUMA cell this point. We can validate this by querying the nova database. For
example (with object versioning fields removed):

.. code-block:: bash

  $ mysql -u root -p123456 nova_cell1
  MariaDB [nova]> select numa_topology from compute_nodes;
  +----------------------------------------------------------------------------+
  | numa_topology                                                              |
  +----------------------------------------------------------------------------+
  | {
  |     "nova_object.name": "NUMATopology",
  |     "nova_object.namespace": "nova",
  |     "nova_object.version": "1.2",
  |     "nova_object.data": {
  |         "cells": [{
  |             "nova_object.name": "NUMACell",
  |             "nova_object.namespace": "nova",
  |             "nova_object.version": "1.4",
  |             "nova_object.data": {
  |                 "id": 0,
  |                 "cpuset": [0, 1, 2, 3, 4, 5, 6, 7],
  |                 "pcpuset": [0, 1, 2, 3, 4, 5, 6, 7],
  |                 "memory": 7975,
  |                 "cpu_usage": 0,
  |                 "memory_usage": 0,
  |                 "pinned_cpus": [],
  |                 "siblings": [
  |                     [0],
  |                     [1],
  |                     [2],
  |                     [3],
  |                     [4],
  |                     [5],
  |                     [6],
  |                     [7]
  |                 ],
  |                 "mempages": [{
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 4,
  |                         "total": 2041795,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["size_kb", "total", "reserved", "used"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 2048,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["size_kb", "total", "reserved", "used"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 1048576,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["size_kb", "total", "reserved", "used"]
  |                 }],
  |                 "network_metadata": {
  |                     "nova_object.name": "NetworkMetadata",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.0",
  |                     "nova_object.data": {
  |                         "physnets": [],
  |                         "tunneled": false
  |                     },
  |                     "nova_object.changes": ["tunneled", "physnets"]
  |                 }
  |             },
  |             "nova_object.changes": ["pinned_cpus", "memory_usage", "siblings", "mempages", "memory", "id", "network_metadata", "cpuset", "cpu_usage", "pcpuset"]
  |         }]
  |     },
  |     "nova_object.changes": ["cells"]
  | }
  +----------------------------------------------------------------------------+

Meanwhile, the guest instance should not have any NUMA configuration recorded:

.. code-block:: bash

  MariaDB [nova]> select numa_topology from instance_extra;
  +---------------+
  | numa_topology |
  +---------------+
  | NULL          |
  +---------------+

-----------------------------------------------------
Reconfiguring the test instance to have NUMA topology
-----------------------------------------------------

Now that devstack is proved operational, it is time to configure some NUMA
topology for the test VM, so that it can be used to verify the OpenStack NUMA
support. To do the changes, the VM instance that is running devstack must be
shut down:

.. code-block:: bash

  $ sudo shutdown -h now

And now back on the physical host edit the guest config as root:

.. code-block:: bash

  $ sudo virsh edit f29x86_64

The first thing is to change the `<cpu>` block to do passthrough of the host
CPU. In particular this exposes the "SVM" or "VMX" feature bits to the guest so
that "Nested KVM" can work. At the same time we want to define the NUMA
topology of the guest. To make things interesting we're going to give the guest
an asymmetric topology with 4 CPUS and 4 GBs of RAM in the first NUMA node and
2 CPUs and 2 GB of RAM in the second and third NUMA nodes. So modify the guest
XML to include the following CPU XML:

.. code-block:: xml

  <cpu mode='host-passthrough'>
    <numa>
      <cell id='0' cpus='0-3' memory='4096000'/>
      <cell id='1' cpus='4-5' memory='2048000'/>
      <cell id='2' cpus='6-7' memory='2048000'/>
    </numa>
  </cpu>

Now start the guest again:

.. code-block:: bash

  # virsh start f29x86_64

...and login back in:

.. code-block:: bash

  # ssh <IP of VM>

Before starting OpenStack services again, it is necessary to explicitly set the
libvirt virtualization type to KVM, so that guests can take advantage of nested
KVM:

.. code-block:: bash

  $ sudo sed -i 's/virt_type = qemu/virt_type = kvm/g' /etc/nova/nova.conf

With that done, OpenStack can be started again:

.. code-block:: bash

  $ cd devstack
  $ ./stack.sh

The first thing is to check that the compute node picked up the new NUMA
topology setup for the guest:

.. code-block:: bash

  $ mysql -u root -p123456 nova_cell1
  MariaDB [nova]> select numa_topology from compute_nodes;
  +----------------------------------------------------------------------------+
  | numa_topology                                                              |
  +----------------------------------------------------------------------------+
  | {
  |     "nova_object.name": "NUMATopology",
  |     "nova_object.namespace": "nova",
  |     "nova_object.version": "1.2",
  |     "nova_object.data": {
  |         "cells": [{
  |             "nova_object.name": "NUMACell",
  |             "nova_object.namespace": "nova",
  |             "nova_object.version": "1.4",
  |             "nova_object.data": {
  |                 "id": 0,
  |                 "cpuset": [0, 1, 2, 3],
  |                 "pcpuset": [0, 1, 2, 3],
  |                 "memory": 3966,
  |                 "cpu_usage": 0,
  |                 "memory_usage": 0,
  |                 "pinned_cpus": [],
  |                 "siblings": [
  |                     [2],
  |                     [0],
  |                     [3],
  |                     [1]
  |                 ],
  |                 "mempages": [{
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 4,
  |                         "total": 1015418,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 2048,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 1048576,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }],
  |                 "network_metadata": {
  |                     "nova_object.name": "NetworkMetadata",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.0",
  |                     "nova_object.data": {
  |                         "physnets": [],
  |                         "tunneled": false
  |                     },
  |                     "nova_object.changes": ["physnets", "tunneled"]
  |                 }
  |             },
  |             "nova_object.changes": ["pinned_cpus", "siblings", "memory", "id", "cpuset", "network_metadata", "pcpuset", "mempages", "cpu_usage", "memory_usage"]
  |         }, {
  |             "nova_object.name": "NUMACell",
  |             "nova_object.namespace": "nova",
  |             "nova_object.version": "1.4",
  |             "nova_object.data": {
  |                 "id": 1,
  |                 "cpuset": [4, 5],
  |                 "pcpuset": [4, 5],
  |                 "memory": 1994,
  |                 "cpu_usage": 0,
  |                 "memory_usage": 0,
  |                 "pinned_cpus": [],
  |                 "siblings": [
  |                     [5],
  |                     [4]
  |                 ],
  |                 "mempages": [{
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 4,
  |                         "total": 510562,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 2048,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 1048576,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }],
  |                 "network_metadata": {
  |                     "nova_object.name": "NetworkMetadata",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.0",
  |                     "nova_object.data": {
  |                         "physnets": [],
  |                         "tunneled": false
  |                     },
  |                     "nova_object.changes": ["physnets", "tunneled"]
  |                 }
  |             },
  |             "nova_object.changes": ["pinned_cpus", "siblings", "memory", "id", "cpuset", "network_metadata", "pcpuset", "mempages", "cpu_usage", "memory_usage"]
  |         }, {
  |             "nova_object.name": "NUMACell",
  |             "nova_object.namespace": "nova",
  |             "nova_object.version": "1.4",
  |             "nova_object.data": {
  |                 "id": 2,
  |                 "cpuset": [6, 7],
  |                 "pcpuset": [6, 7],
  |                 "memory": 2014,
  |                 "cpu_usage": 0,
  |                 "memory_usage": 0,
  |                 "pinned_cpus": [],
  |                 "siblings": [
  |                     [7],
  |                     [6]
  |                 ],
  |                 "mempages": [{
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 4,
  |                         "total": 515727,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 2048,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }, {
  |                     "nova_object.name": "NUMAPagesTopology",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.1",
  |                     "nova_object.data": {
  |                         "size_kb": 1048576,
  |                         "total": 0,
  |                         "used": 0,
  |                         "reserved": 0
  |                     },
  |                     "nova_object.changes": ["total", "size_kb", "used", "reserved"]
  |                 }],
  |                 "network_metadata": {
  |                     "nova_object.name": "NetworkMetadata",
  |                     "nova_object.namespace": "nova",
  |                     "nova_object.version": "1.0",
  |                     "nova_object.data": {
  |                         "physnets": [],
  |                         "tunneled": false
  |                     },
  |                     "nova_object.changes": ["physnets", "tunneled"]
  |                 }
  |             },
  |             "nova_object.changes": ["pinned_cpus", "siblings", "memory", "id", "cpuset", "network_metadata", "pcpuset", "mempages", "cpu_usage", "memory_usage"]
  |         }]
  |     },
  |     "nova_object.changes": ["cells"]
  +----------------------------------------------------------------------------+

This indeed shows that there are now 3 NUMA nodes for the "host" machine, the
first with 4 GB of RAM and 4 CPUs, and others with 2 GB of RAM and 2 CPUs each.

-----------------------------------------------------
Testing instance boot with no NUMA topology requested
-----------------------------------------------------

For the sake of backwards compatibility, if the NUMA filter is enabled, but the
flavor/image does not have any NUMA settings requested, it should be assumed
that the guest will have a single NUMA node. The guest should be locked to a
single host NUMA node too. Boot a guest with the `m1.tiny` flavor to test this
condition:

.. code-block:: bash

  $ . openrc admin admin
  $ openstack server create --image cirros-0.4.0-x86_64-disk --flavor m1.tiny \
      cirros1

Now look at the libvirt guest XML:

.. code-block:: bash

  $ sudo virsh list
   Id    Name                           State
  ----------------------------------------------------
   1     instance-00000001              running
  $ sudo virsh dumpxml instance-00000001
  ...
  <vcpu placement='static'>1</vcpu>
  ...

This example shows that there is no explicit NUMA topology listed in the guest
XML.

------------------------------------------------
Testing instance boot with 1 NUMA cell requested
------------------------------------------------

Moving forward a little, explicitly tell nova that the NUMA topology for the
guest should have a single NUMA node. This should operate in an identical
manner to the default behavior where no NUMA policy is set. To define the
topology we will create a new flavor:

.. code-block:: bash

  $ openstack flavor create --ram 1024 --disk 1 --vcpus 4 m1.numa
  $ openstack flavor set --property hw:numa_nodes=1 m1.numa
  $ openstack flavor show m1.numa

Now boot the guest using this new flavor:

.. code-block:: bash

  $ openstack server create --image cirros-0.4.0-x86_64-disk --flavor m1.numa \
      cirros2

Looking at the resulting guest XML from libvirt:

.. code-block:: bash

  $ sudo virsh list
   Id    Name                           State
  ----------------------------------------------------
   1     instance-00000001              running
   2     instance-00000002              running
  $ sudo virsh dumpxml instance-00000002
  ...
  <vcpu placement='static'>4</vcpu>
  <cputune>
    <vcpupin vcpu='0' cpuset='0-3'/>
    <vcpupin vcpu='1' cpuset='0-3'/>
    <vcpupin vcpu='2' cpuset='0-3'/>
    <vcpupin vcpu='3' cpuset='0-3'/>
    <emulatorpin cpuset='0-3'/>
  </cputune>
  ...
  <cpu>
    <topology sockets='4' cores='1' threads='1'/>
    <numa>
      <cell id='0' cpus='0-3' memory='1048576'/>
    </numa>
  </cpu>
  ...
  <numatune>
    <memory mode='strict' nodeset='0'/>
    <memnode cellid='0' mode='strict' nodeset='0'/>
  </numatune>

The XML shows:

* Each guest CPU has been pinned to the physical CPUs associated with a
  particular NUMA node

* The emulator threads have been pinned to the union of all physical CPUs in
  the host NUMA node that the guest is placed on

* The guest has been given a virtual NUMA topology with a single node holding
  all RAM and CPUs

* The guest NUMA node has been strictly pinned to a host NUMA node.

As a further sanity test, check what nova recorded for the instance in the
database. This should match the ``<numatune>`` information:

.. code-block:: bash

  $ mysql -u root -p123456 nova_cell1
  MariaDB [nova]> select numa_topology from instance_extra;
  +----------------------------------------------------------------------------+
  | numa_topology                                                              |
  +----------------------------------------------------------------------------+
  | {
  |     "nova_object.name": "InstanceNUMATopology",
  |     "nova_object.namespace": "nova",
  |     "nova_object.version": "1.3",
  |     "nova_object.data": {
  |         "cells": [{
  |             "nova_object.name": "InstanceNUMACell",
  |             "nova_object.namespace": "nova",
  |             "nova_object.version": "1.4",
  |             "nova_object.data": {
  |                 "id": 0,
  |                 "cpuset": [0, 1, 2, 3],
  |                 "memory": 1024,
  |                 "pagesize": null,
  |                 "cpu_pinning_raw": null,
  |                 "cpu_policy": null,
  |                 "cpu_thread_policy": null,
  |                 "cpuset_reserved": null
  |             },
  |             "nova_object.changes": ["id"]
  |         }],
  |         "emulator_threads_policy": null
  |     },
  |     "nova_object.changes": ["cells", "emulator_threads_policy"]
  | }
  +----------------------------------------------------------------------------+

Delete this instance:

.. code-block:: bash

  $ openstack server delete cirros2

-------------------------------------------------
Testing instance boot with 2 NUMA cells requested
-------------------------------------------------

Now getting more advanced we tell nova that the guest will have two NUMA nodes.
To define the topology we will change the previously defined flavor:

.. code-block:: bash

  $ openstack flavor set --property hw:numa_nodes=2 m1.numa
  $ openstack flavor show m1.numa

Now boot the guest using this changed flavor:

.. code-block:: bash

  $ openstack server create --image cirros-0.4.0-x86_64-disk --flavor m1.numa \
      cirros2

Looking at the resulting guest XML from libvirt:

.. code-block:: bash

  $ sudo virsh list
   Id    Name                           State
  ----------------------------------------------------
   1     instance-00000001              running
   3     instance-00000003              running
  $ sudo virsh dumpxml instance-00000003
  ...
  <vcpu placement='static'>4</vcpu>
  <cputune>
    <vcpupin vcpu='0' cpuset='0-3'/>
    <vcpupin vcpu='1' cpuset='0-3'/>
    <vcpupin vcpu='2' cpuset='4-5'/>
    <vcpupin vcpu='3' cpuset='4-5'/>
    <emulatorpin cpuset='0-5'/>
  </cputune>
  ...
  <cpu>
    <topology sockets='4' cores='1' threads='1'/>
    <numa>
      <cell id='0' cpus='0-1' memory='524288'/>
      <cell id='1' cpus='2-3' memory='524288'/>
    </numa>
  </cpu>
  ...
  <numatune>
    <memory mode='strict' nodeset='0-1'/>
    <memnode cellid='0' mode='strict' nodeset='0'/>
    <memnode cellid='1' mode='strict' nodeset='1'/>
  </numatune>

The XML shows:

* Each guest CPU has been pinned to the physical CPUs associated with
  particular NUMA nodes

* The emulator threads have been pinned to the union of all physical CPUs in
  the host NUMA nodes that the guest is placed on

* The guest has been given a virtual NUMA topology with two nodes, each holding
  half the RAM and CPUs

* The guest NUMA nodes have been strictly pinned to different host NUMA node

As a further sanity test, check what nova recorded for the instance in the
database. This should match the ``<numatune>`` information:

.. code-block:: bash

  MariaDB [nova]> select numa_topology from instance_extra;
  +----------------------------------------------------------------------------+
  | numa_topology                                                              |
  +----------------------------------------------------------------------------+
  | {
  |     "nova_object.name": "InstanceNUMATopology",
  |     "nova_object.namespace": "nova",
  |     "nova_object.version": "1.3",
  |     "nova_object.data": {
  |         "cells": [{
  |             "nova_object.name": "InstanceNUMACell",
  |             "nova_object.namespace": "nova",
  |             "nova_object.version": "1.4",
  |             "nova_object.data": {
  |                 "id": 0,
  |                 "cpuset": [0, 1],
  |                 "memory": 512,
  |                 "pagesize": null,
  |                 "cpu_pinning_raw": null,
  |                 "cpu_policy": null,
  |                 "cpu_thread_policy": null,
  |                 "cpuset_reserved": null
  |             },
  |             "nova_object.changes": ["id"]
  |         }, {
  |             "nova_object.name": "InstanceNUMACell",
  |             "nova_object.namespace": "nova",
  |             "nova_object.version": "1.4",
  |             "nova_object.data": {
  |                 "id": 1,
  |                 "cpuset": [2, 3],
  |                 "memory": 512,
  |                 "pagesize": null,
  |                 "cpu_pinning_raw": null,
  |                 "cpu_policy": null,
  |                 "cpu_thread_policy": null,
  |                 "cpuset_reserved": null
  |             },
  |             "nova_object.changes": ["id"]
  |         }],
  |         "emulator_threads_policy": null
  |     },
  |     "nova_object.changes": ["cells", "emulator_threads_policy"]
  | }
  +----------------------------------------------------------------------------+
