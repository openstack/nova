=======
Compute
=======

The OpenStack Compute service allows you to control an
Infrastructure-as-a-Service (IaaS) cloud computing platform.  It gives you
control over instances and networks, and allows you to manage access to the
cloud through users and projects.

Compute does not include virtualization software. Instead, it defines drivers
that interact with underlying virtualization mechanisms that run on your host
operating system, and exposes functionality over a web-based API.


Overview
--------

To effectively administer compute, you must understand how the different
installed nodes interact with each other. Compute can be installed in many
different ways using multiple servers, but generally multiple compute nodes
control the virtual servers and a cloud controller node contains the remaining
Compute services.

The Compute cloud works using a series of daemon processes named ``nova-*``
that exist persistently on the host machine. These binaries can all run on the
same machine or be spread out on multiple boxes in a large deployment. The
responsibilities of services and drivers are:

.. rubric:: Services

``nova-api``
  Receives XML requests and sends them to the rest of the system. A WSGI app
  routes and authenticates requests. Supports the OpenStack Compute APIs. A
  ``nova.conf`` configuration file is created when Compute is installed.

.. todo::

   Describe nova-api-metadata, nova-api-os-compute, nova-serialproxy and
   nova-spicehtml5proxy

   nova-console, nova-dhcpbridge and nova-xvpvncproxy are all deprecated for
   removal so they can be ignored.

``nova-compute``
  Manages virtual machines. Loads a Service object, and exposes the public
  methods on ComputeManager through a Remote Procedure Call (RPC).

``nova-conductor``
  Provides database-access support for compute nodes (thereby reducing security
  risks).

``nova-scheduler``
  Dispatches requests for new virtual machines to the correct node.

``nova-novncproxy``
  Provides a VNC proxy for browsers, allowing VNC consoles to access virtual
  machines.

.. note::

   Some services have drivers that change how the service implements its core
   functionality. For example, the ``nova-compute`` service supports drivers
   that let you choose which hypervisor type it can use.

.. toctree::
   :maxdepth: 2

   manage-volumes
   flavors
   default-ports
   admin-password-injection
   manage-the-cloud
   manage-logs
   root-wrap-reference
   configuring-migrations
   live-migration-usage
   remote-console-access
   service-groups
   node-down


Advanced configuration
----------------------

OpenStack clouds run on platforms that differ greatly in the capabilities that
they provide. By default, the Compute service seeks to abstract the underlying
hardware that it runs on, rather than exposing specifics about the underlying
host platforms. This abstraction manifests itself in many ways. For example,
rather than exposing the types and topologies of CPUs running on hosts, the
service exposes a number of generic CPUs (virtual CPUs, or vCPUs) and allows
for overcommitting of these. In a similar manner, rather than exposing the
individual types of network devices available on hosts, generic
software-powered network ports are provided. These features are designed to
allow high resource utilization and allows the service to provide a generic
cost-effective and highly scalable cloud upon which to build applications.

This abstraction is beneficial for most workloads. However, there are some
workloads where determinism and per-instance performance are important, if not
vital. In these cases, instances can be expected to deliver near-native
performance. The Compute service provides features to improve individual
instance for these kind of workloads.

.. include:: /common/numa-live-migration-warning.txt

.. toctree::
   :maxdepth: 2

   pci-passthrough
   cpu-topologies
   huge-pages
   virtual-gpu
   file-backed-memory
   ports-with-resource-requests
   virtual-persistent-memory


Additional guides
-----------------

.. TODO(mriedem): This index page has a lot of content which should be
   organized into groups for things like configuration, operations,
   troubleshooting, etc.

.. toctree::
   :maxdepth: 2

   aggregates
   arch
   availability-zones
   cells
   config-drive
   configuration/index
   evacuate
   image-caching
   metadata-service
   migration
   migrate-instance-with-snapshot
   networking
   quotas
   security-groups
   security
   services
   ssh-configuration
   support-compute
   secure-live-migration-with-qemu-native-tls
   mitigation-for-Intel-MDS-security-flaws
   vendordata
