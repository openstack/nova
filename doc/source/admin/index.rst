===================
Admin Documentation
===================

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

:doc:`nova-api-metadata </cli/nova-api-metadata>`
  A server daemon that serves the Nova Metadata API.

:doc:`nova-api-os-compute </cli/nova-api-os-compute>`
  A server daemon that serves the Nova OpenStack Compute API.

:doc:`nova-api </cli/nova-api>`
  A server daemon that serves the metadata and compute APIs in separate
  greenthreads.

:doc:`nova-compute </cli/nova-compute>`
  Manages virtual machines. Loads a Service object, and exposes the public
  methods on ComputeManager through a Remote Procedure Call (RPC).

:doc:`nova-conductor </cli/nova-conductor>`
  Provides database-access support for compute nodes (thereby reducing security
  risks).

:doc:`nova-scheduler </cli/nova-scheduler>`
  Dispatches requests for new virtual machines to the correct node.

:doc:`nova-novncproxy </cli/nova-novncproxy>`
  Provides a VNC proxy for browsers, allowing VNC consoles to access virtual
  machines.

:doc:`nova-spicehtml5proxy </cli/nova-spicehtml5proxy>`
  Provides a SPICE proxy for browsers, allowing SPICE consoles to access
  virtual machines.

:doc:`nova-serialproxy </cli/nova-serialproxy>`
  Provides a serial console proxy, allowing users to access a virtual machine's
  serial console.

The architecture is covered in much greater detail in
:doc:`/admin/architecture`.

.. toctree::
   :maxdepth: 2

   architecture

.. note::

   Some services have drivers that change how the service implements its core
   functionality. For example, the ``nova-compute`` service supports drivers
   that let you choose which hypervisor type it can use.


Deployment Considerations
-------------------------

There is information you might want to consider before doing your deployment,
especially if it is going to be a larger deployment. For smaller deployments
the defaults from the :doc:`install guide </install/index>` will be sufficient.

* **Compute Driver Features Supported**: While the majority of nova deployments use
  libvirt/kvm, you can use nova with other compute drivers. Nova attempts to
  provide a unified feature set across these, however, not all features are
  implemented on all backends, and not all features are equally well tested.

  * :doc:`Feature Support by Use Case </user/feature-classification>`: A view of
    what features each driver supports based on what's important to some large
    use cases (General Purpose Cloud, NFV Cloud, HPC Cloud).

  * :doc:`Feature Support full list </user/support-matrix>`: A detailed dive through
    features in each compute driver backend.

* :doc:`Cells v2 configuration </admin/cells>`: For large deployments, cells v2
  cells allow sharding of your compute environment. Upfront planning is key to
  a successful cells v2 layout.

* :doc:`Availability Zones </admin/availability-zones>`: Availability Zones are
  an end-user visible logical abstraction for partitioning a cloud without
  knowing the physical infrastructure.

* :placement-doc:`Placement service <>`: Overview of the placement
  service, including how it fits in with the rest of nova.

* :doc:`Running nova-api on wsgi </user/wsgi>`: Considerations for using a real
  WSGI container instead of the baked-in eventlet web server.

.. toctree::
   :maxdepth: 2

   cells
   aggregates
   default-ports
   availability-zones
   configuration/index


Basic configuration
-------------------

Once you have an OpenStack deployment up and running, you will want to manage
it. The below guides cover everything from creating initial flavor and image to
log management and live migration of instances.

* :doc:`Quotas </admin/quotas>`: Managing project quotas in nova.

* :doc:`Scheduling </admin/scheduling>`: How the scheduler is
  configured, and how that will impact where compute instances land in your
  environment. If you are seeing unexpected distribution of compute instances
  in your hosts, you'll want to dive into this configuration.

* :doc:`Exposing custom metadata to compute instances </admin/vendordata>`: How
  and when you might want to extend the basic metadata exposed to compute
  instances (either via metadata server or config drive) for your specific
  purposes.

.. toctree::
   :maxdepth: 2

   manage-the-cloud
   services
   service-groups
   manage-logs
   root-wrap-reference
   ssh-configuration
   configuring-migrations
   live-migration-usage
   secure-live-migration-with-qemu-native-tls
   manage-volumes
   flavors
   admin-password-injection
   remote-console-access
   scheduling
   config-drive
   image-caching
   metadata-service
   quotas
   networking
   security-groups
   security
   vendordata
   notifications


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
   real-time
   huge-pages
   virtual-gpu
   file-backed-memory
   ports-with-resource-requests
   vdpa
   virtual-persistent-memory
   emulated-tpm
   uefi
   secure-boot
   sev
   managing-resource-providers
   compute-node-identification
   resource-limits
   cpu-models
   libvirt-misc


Maintenance
-----------

Once you are running nova, the following information is extremely useful.

* :doc:`Upgrades <upgrades>`: How nova is designed to be upgraded for minimal
  service impact, and the order you should do them in.

.. toctree::
   :maxdepth: 2

   support-compute
   evacuate
   migration
   migrate-instance-with-snapshot
   upgrades
   node-down
   hw-machine-type
   hw-emulation-architecture
   soft-delete-shadow-tables
