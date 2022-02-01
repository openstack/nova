========================
Nova System Architecture
========================

Nova comprises multiple server processes, each performing different
functions. The user-facing interface is a REST API, while internally Nova
components communicate via an RPC message passing mechanism.

The API servers process REST requests, which typically involve database
reads/writes, optionally sending RPC messages to other Nova services,
and generating responses to the REST calls.
RPC messaging is done via the **oslo.messaging** library,
an abstraction on top of message queues.
Nova uses a messaging-based, "shared nothing" architecture and most of the
major nova components can be run on multiple servers, and have a manager that
is listening for RPC messages.
The one major exception is the compute service, where a single process runs on the
hypervisor it is managing (except when using the VMware or Ironic drivers).
The manager also, optionally, has periodic tasks.
For more details on our RPC system, refer to :doc:`/reference/rpc`.

Nova uses traditional SQL databases to store information.
These are (logically) shared between multiple components.
To aid upgrade, the database is accessed through an object layer that ensures
an upgraded control plane can still communicate with a compute nodes running
the previous release.
To make this possible, services running on the compute node proxy database
requests over RPC to a central manager called the conductor.

To horizontally expand Nova deployments, we have a deployment sharding
concept called :term:`cells <cell>`.
All deployments contain at least one cell.
For more information, refer to :doc:`/admin/cells`.


Components
----------

Below you will find a helpful explanation of the key components
of a typical Nova deployment.

.. image:: /_static/images/architecture.svg
   :width: 100%

* **DB**: SQL database for data storage.

* **API**: Component that receives HTTP requests, converts commands and
  communicates with other components via the **oslo.messaging** queue or HTTP.

* **Scheduler**: Decides which host gets each instance.

* **Compute**: Manages communication with hypervisor and virtual machines.

* **Conductor**: Handles requests that need coordination (build/resize), acts
  as a database proxy, or handles object conversions.

* **:placement-doc:`Placement <>`**: Tracks resource provider inventories and
  usages.

While all services are designed to be horizontally scalable, you should have
significantly more computes than anything else.


Hypervisors
-----------

Nova controls hypervisors through an API server. Selecting the best
hypervisor to use can be difficult, and you must take budget, resource
constraints, supported features, and required technical specifications into
account. However, the majority of OpenStack development is done on systems
using KVM-based hypervisors. For a detailed list of features and
support across different hypervisors, see :doc:`/user/support-matrix`.

You can also orchestrate clouds using multiple hypervisors in different
availability zones. Nova supports the following hypervisors:

- :ironic-doc:`Baremetal <>`

- `Hyper-V
  <https://docs.microsoft.com/en-us/windows-server/virtualization/hyper-v/hyper-v-technology-overview>`__

- `Kernel-based Virtual Machine (KVM)
  <https://www.linux-kvm.org/page/Main_Page>`__

- `Linux Containers (LXC) <https://linuxcontainers.org>`__

- `PowerVM <https://www.ibm.com/us-en/marketplace/ibm-powervm>`__

- `Quick Emulator (QEMU) <https://wiki.qemu.org/Manual>`__

- `Virtuozzo <https://www.virtuozzo.com/products/vz7.html>`__

- `VMware vSphere
  <https://www.vmware.com/support/vsphere-hypervisor.html>`__


- `zVM <https://www.ibm.com/it-infrastructure/z/zvm>`__

For more information about hypervisors, see
:doc:`/admin/configuration/hypervisors`
section in the Nova Configuration Reference.


Projects, users, and roles
--------------------------

To begin using Nova, you must create a user with the
:keystone-doc:`Identity service <>`.

The Nova system is designed to be used by different consumers in the form of
projects on a shared system, and role-based access assignments. Roles control
the actions that a user is allowed to perform.

Projects are isolated resource containers that form the principal
organizational structure within the Nova service. They typically consist of
networks, volumes, instances, images, keys, and users. A user can
specify the project by appending ``project_id`` to their access key.

For projects, you can use quota controls to limit the number of processor cores
and the amount of RAM that can be allocated. Other projects also allow quotas
on their own resources. For example, :neutron-doc:`neutron
</admin/ops-quotas.html>` allows you to manage the amount of networks that can
be created within a project.

Roles control the actions a user is allowed to perform. By default, most
actions do not require a particular role, but you can configure them by editing
the ``policy.yaml`` file for user roles. For example, a rule can be defined so
that a user must have the ``admin`` role in order to be able to allocate a
public IP address.

A project limits users' access to particular images. Each user is assigned a
user name and password. Keypairs granting access to an instance are enabled for
each user, but quotas are set, so that each project can control resource
consumption across available hardware resources.

.. note::

   Earlier versions of OpenStack used the term ``tenant`` instead of
   ``project``. Because of this legacy terminology, some command-line tools use
   ``--tenant_id`` where you would normally expect to enter a project ID.


Block storage
-------------

OpenStack provides two classes of block storage: storage that is provisioned by
Nova itself, and storage that is managed by the block storage service, Cinder.

.. rubric:: Nova-provisioned block storage

Nova provides the ability to create a root disk and an optional "ephemeral"
volume. The root disk will always be present unless the instance is a
:term:`Boot From Volume` instance.

The root disk is associated with an instance, and exists only for the life of
this very instance. Generally, it is used to store an instance's root file
system, persists across the guest operating system reboots, and is removed on
an instance deletion. The amount of the root ephemeral volume is defined by the
flavor of an instance.

In addition to the root volume, flavors can provide an additional
ephemeral block device. It is represented as a raw block device with no
partition table or file system. A cloud-aware operating system can discover,
format, and mount such a storage device. Nova defines the default file system
for different operating systems as ext4 for Linux distributions, VFAT for
non-Linux and non-Windows operating systems, and NTFS for Windows. However, it
is possible to configure other filesystem types.

.. note::

   For example, the ``cloud-init`` package included into an Ubuntu's stock
   cloud image, by default, formats this space as an ext4 file system and
   mounts it on ``/mnt``. This is a cloud-init feature, and is not an OpenStack
   mechanism. OpenStack only provisions the raw storage.

.. rubric:: Cinder-provisioned block storage

The OpenStack Block Storage service, Cinder, provides persistent volumes hat
are represented by a persistent virtualized block device independent of any
particular instance.

Persistent volumes can be accessed by a single instance or attached to multiple
instances. This type of configuration requires a traditional network file
system to allow multiple instances accessing the persistent volume. It also
requires a traditional network file system like NFS, CIFS, or a cluster file
system such as Ceph. These systems can be built within an OpenStack
cluster, or provisioned outside of it, but OpenStack software does not provide
these features.

You can configure a persistent volume as bootable and use it to provide a
persistent virtual instance similar to the traditional non-cloud-based
virtualization system. It is still possible for the resulting instance to keep
ephemeral storage, depending on the flavor selected. In this case, the root
file system can be on the persistent volume, and its state is maintained, even
if the instance is shut down. For more information about this type of
configuration, see :cinder-doc:`Introduction to the Block Storage service
<configuration/block-storage/block-storage-overview.html>`.


Building blocks
---------------

In OpenStack the base operating system is usually copied from an image stored
in the OpenStack Image service, glance. This is the most common case and
results in an ephemeral instance that starts from a known template state and
loses all accumulated states on virtual machine deletion. It is also possible
to put an operating system on a persistent volume in the OpenStack Block
Storage service. This gives a more traditional persistent system that
accumulates states which are preserved on the OpenStack Block Storage volume
across the deletion and re-creation of the virtual machine. To get a list of
available images on your system, run:

.. code-block:: console

   $ openstack image list
   +--------------------------------------+-----------------------------+--------+
   | ID                                   | Name                        | Status |
   +--------------------------------------+-----------------------------+--------+
   | aee1d242-730f-431f-88c1-87630c0f07ba | Ubuntu 14.04 cloudimg amd64 | active |
   | 0b27baa1-0ca6-49a7-b3f4-48388e440245 | Ubuntu 14.10 cloudimg amd64 | active |
   | df8d56fc-9cea-4dfd-a8d3-28764de3cb08 | jenkins                     | active |
   +--------------------------------------+-----------------------------+--------+

The displayed image attributes are:

``ID``
  Automatically generated UUID of the image

``Name``
  Free form, human-readable name for image

``Status``
  The status of the image. Images marked ``ACTIVE`` are available for use.

``Server``
  For images that are created as snapshots of running instances, this is the
  UUID of the instance the snapshot derives from. For uploaded images, this
  field is blank.

Virtual hardware templates are called ``flavors``. By default, these are
configurable by admin users, however, that behavior can be changed by redefining
the access controls ``policy.yaml`` on the ``nova-api`` server. For more
information, refer to :doc:`/configuration/policy`.

For a list of flavors that are available on your system:

.. code-block:: console

   $ openstack flavor list
   +-----+-----------+-------+------+-----------+-------+-----------+
   | ID  | Name      |   RAM | Disk | Ephemeral | VCPUs | Is_Public |
   +-----+-----------+-------+------+-----------+-------+-----------+
   | 1   | m1.tiny   |   512 |    1 |         0 |     1 | True      |
   | 2   | m1.small  |  2048 |   20 |         0 |     1 | True      |
   | 3   | m1.medium |  4096 |   40 |         0 |     2 | True      |
   | 4   | m1.large  |  8192 |   80 |         0 |     4 | True      |
   | 5   | m1.xlarge | 16384 |  160 |         0 |     8 | True      |
   +-----+-----------+-------+------+-----------+-------+-----------+


Nova service architecture
-------------------------

These basic categories describe the service architecture and information about
the cloud controller.

.. rubric:: API server

At the heart of the cloud framework is an API server, which makes command and
control of the hypervisor, storage, and networking programmatically available
to users.

The API endpoints are basic HTTP web services which handle authentication,
authorization, and basic command and control functions using various API
interfaces under the Amazon, Rackspace, and related models. This enables API
compatibility with multiple existing tool sets created for interaction with
offerings from other vendors. This broad compatibility prevents vendor lock-in.

.. rubric:: Message queue

A messaging queue brokers the interaction between compute nodes (processing),
the networking controllers (software which controls network infrastructure),
API endpoints, the scheduler (determines which physical hardware to allocate to
a virtual resource), and similar components. Communication to and from the
cloud controller is handled by HTTP requests through multiple API endpoints.

A typical message passing event begins with the API server receiving a request
from a user. The API server authenticates the user and ensures that they are
permitted to issue the subject command. The availability of objects implicated
in the request is evaluated and, if available, the request is routed to the
queuing engine for the relevant workers.  Workers continually listen to the
queue based on their role, and occasionally their type host name. When an
applicable work request arrives on the queue, the worker takes assignment of
the task and begins executing it. Upon completion, a response is dispatched to
the queue which is received by the API server and relayed to the originating
user.  Database entries are queried, added, or removed as necessary during the
process.

.. rubric:: Compute worker

Compute workers manage computing instances on host machines. The API dispatches
commands to compute workers to complete these tasks:

-  Run instances

-  Delete instances (Terminate instances)

-  Reboot instances

-  Attach volumes

-  Detach volumes

-  Get console output

.. rubric:: Network Controller

The Network Controller manages the networking resources on host machines. The
API server dispatches commands through the message queue, which are
subsequently processed by Network Controllers. Specific operations include:

-  Allocating fixed IP addresses

-  Configuring VLANs for projects

-  Configuring networks for compute nodes
