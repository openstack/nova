.. _compute-trusted-pools.rst:

=====================
System administration
=====================

.. toctree::
   :maxdepth: 2

   manage-users.rst
   manage-volumes.rst
   flavors.rst
   default-ports.rst
   admin-password-injection.rst
   manage-the-cloud.rst
   manage-logs.rst
   root-wrap-reference.rst
   configuring-migrations.rst
   live-migration-usage.rst
   remote-console-access.rst
   service-groups.rst
   node-down.rst
   adv-config.rst

To effectively administer compute, you must understand how the different
installed nodes interact with each other. Compute can be installed in many
different ways using multiple servers, but generally multiple compute nodes
control the virtual servers and a cloud controller node contains the remaining
Compute services.

The Compute cloud works using a series of daemon processes named ``nova-*``
that exist persistently on the host machine. These binaries can all run on the
same machine or be spread out on multiple boxes in a large deployment. The
responsibilities of services and drivers are:

**Services**

``nova-api``
  Receives XML requests and sends them to the rest of the system. A WSGI app
  routes and authenticates requests. Supports the OpenStack Compute APIs. A
  ``nova.conf`` configuration file is created when Compute is installed.

``nova-cert``
  Manages certificates.

``nova-compute``
  Manages virtual machines. Loads a Service object, and exposes the public
  methods on ComputeManager through a Remote Procedure Call (RPC).

``nova-conductor``
  Provides database-access support for compute nodes (thereby reducing security
  risks).

``nova-consoleauth``
  Manages console authentication.

``nova-objectstore``
  A simple file-based storage system for images that replicates most of the S3
  API. It can be replaced with OpenStack Image service and either a simple
  image manager or OpenStack Object Storage as the virtual machine image
  storage facility. It must exist on the same node as ``nova-compute``.

``nova-network``
  Manages floating and fixed IPs, DHCP, bridging and VLANs. Loads a Service
  object which exposes the public methods on one of the subclasses of
  NetworkManager. Different networking strategies are available by changing the
  ``network_manager`` configuration option to ``FlatManager``,
  ``FlatDHCPManager``, or ``VLANManager`` (defaults to ``VLANManager`` if
  nothing is specified).

``nova-scheduler``
  Dispatches requests for new virtual machines to the correct node.

``nova-novncproxy``
  Provides a VNC proxy for browsers, allowing VNC consoles to access virtual
  machines.

.. note::

   Some services have drivers that change how the service implements its core
   functionality. For example, the ``nova-compute`` service supports drivers
   that let you choose which hypervisor type it can use. ``nova-network`` and
   ``nova-scheduler`` also have drivers.
