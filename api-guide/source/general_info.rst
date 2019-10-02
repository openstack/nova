========================
Key Compute API Concepts
========================

The OpenStack Compute API is defined as a RESTful HTTP service. The API
takes advantage of all aspects of the HTTP protocol (methods, URIs,
media types, response codes, etc.) and providers are free to use
existing features of the protocol such as caching, persistent
connections, and content compression among others.

Providers can return information identifying requests in HTTP response
headers, for example, to facilitate communication between the provider
and client applications.

OpenStack Compute is a compute service that provides server capacity in
the cloud. Compute Servers come in different flavors of memory, cores,
disk space, and CPU, and can be provisioned in minutes. Interactions
with Compute Servers can happen programmatically with the OpenStack
Compute API.

User Concepts
=============

To use the OpenStack Compute API effectively, you should understand
several key concepts:

-  **Server**

   A virtual machine (VM) instance, physical machine or a container in the
   compute system. Flavor and image are requisite elements when creating a
   server. A name for the server is also required.

   For more details, such as server actions and server metadata,
   please see: :doc:`server_concepts`

-  **Flavor**

   Virtual hardware configuration for the requested server. Each flavor has a
   unique combination of disk space, memory capacity and priority for
   CPU time.

-  **Flavor Extra Specs**

   Key and value pairs that can be used to describe the specification of
   the server which is more than just about CPU, disk and RAM. For example,
   it can be used to indicate that the server created by this flavor has
   PCI devices, etc.

   For more details, please see: :doc:`extra_specs_and_properties`

-  **Image**

   A collection of files used to create or rebuild a server. Operators
   provide a number of pre-built OS images by default. You may also
   create custom images from cloud servers you have launched. These
   custom images are useful for backup purposes or for producing "gold"
   server images if you plan to deploy a particular server configuration
   frequently.

-  **Image Properties**

   Key and value pairs that can help end users to determine the requirements
   of the guest operating system in the image.

   For more details, please see: :doc:`extra_specs_and_properties`

-  **Key Pair**

   An ssh or x509 keypair that can be injected into a server at it's boot time.
   This allows you to connect to your server once it has been created without
   having to use a password. If you don't specify a key pair, Nova will create
   a root password for you, and return it in plain text in the server create
   response.

-  **Volume**

   A block storage device that Nova can use as permanent storage. When a server
   is created it has some disk storage available, but that is considered
   ephemeral, as it is destroyed when the server is destroyed. A volume can be
   attached to a server, then later detached and used by another server.
   Volumes are created and managed by the Cinder service.
   For additional info, see
   :nova-doc:`Block device mapping <user/block-device-mapping.html>`

-  **Quotas**

   An upper limit on the amount of resources any individual tenant may consume.
   Quotas can be used to limit the number of servers a tenant creates, or the
   amount of disk space consumed, so that no one tenant can overwhelm the
   system and prevent normal operation for others. Changing quotas is an
   administrator-level action. For additional info,
   see :nova-doc:`Quotas <user/quotas.html>`

-  **Rate Limiting**

   Please see :doc:`limits`

-  **Availability zone**

   A grouping of host machines that can be used to control where a new server
   is created. There is some confusion about this, as the name "availability
   zone" is used in other clouds, such as Amazon Web Services, to denote a
   physical separation of server locations that can be used to distribute cloud
   resources for fault tolerance in case one zone is unavailable for any
   reason. Such a separation is possible in Nova if an administrator carefully
   sets up availability zones for that, but it is not the default.

Networking Concepts
-------------------

Networking is handled by the :neutron-doc:`networking service <>`. When working
with a server in the compute service, the most important networking resource
is a *port* which is part of a *network*. Ports can have *security groups*
applied to control firewall access. Ports can also be linked to *floating IPs*
for external network access depending on the networking service configuration.

When creating a server or attaching a network interface to an existing server,
zero or more networks and/or ports can be specified to attach to the server.
If nothing is provided, the compute service will by default create a port on
the single network available to the project making the request. If more than
one network is available to the project, such as a public external network and
a private tenant network, an error will occur and the request will have to be
made with a specific network or port. If a network is specified the compute
service will attempt to create a port on the given network on behalf of the
user. More advanced types of ports, such as
:neutron-doc:`SR-IOV ports </admin/config-sriov>`, must be pre-created and
provided to the compute service.

Refer to the `network API reference`_ for more details.

.. _network API reference: https://docs.openstack.org/api-ref/network/


Administrator Concepts
======================

Some APIs are largely focused on administration of Nova, and generally focus
on compute hosts rather than servers.

-  **Services**

   Services are provided by Nova components. Normally, the Nova component runs
   as a process on the controller/compute node to provide the service. These
   services may be end-user facing, such as the OpenStack Compute REST API
   service, but most just work with other Nova services. The status of each
   service is monitored by Nova, and if it is not responding normally, Nova
   will update its status so that requests are not sent to that service
   anymore. The service can also be controlled by an Administrator in order to
   run maintenance or upgrades, or in response to changing workloads.

   - **nova-osapi_compute**

     This service provides the OpenStack Compute REST API to end users and
     application clients.

   - **nova-metadata**

     This service provides the OpenStack Metadata API to servers. The metadata
     is used to configure the running servers.

   - **nova-scheduler**

     This service provides compute request scheduling by tracking available
     resources, and finding the host that can best fulfill the request.

   - **nova-conductor**

     This service provides database access for Nova and the other OpenStack
     services, and handles internal version compatibility when different
     services are running different versions of code. The conductor service
     also handles long-running requests.

   - **nova-compute**

     This service runs on every compute node, and communicates with a
     hypervisor for managing compute resources on that node.

-  **Services Actions**

   .. note::
      The services actions described in this section apply only to
      **nova-compute** services.

   - **enable, disable, disable-log-reason**

     The service can be disabled to indicate the service is not available anymore.
     This is used by administrator to stop service for maintenance.
     For example, when Administrator wants to maintain a specific compute node,
     Administrator can disable nova-compute service on that compute node. Then
     nova won't dispatch any new compute request to that compute node anymore.
     Administrator also can add note for disable reason.

   - **forced-down**

     .. note::
       This action is enabled in microversion 2.11.

     This action allows you set the state of service down immediately. Nova
     only provides a very basic health monitor of service status, there isn't
     any guarantee about health status of other parts of infrastructure, like
     the health status of data network, storage network and other
     components.

     If you have a more extensive health monitoring system external to Nova,
     and know that the service in question is dead (and disconnected from the
     network), this can be used to tell the rest of Nova it can trust that this
     service is never coming back, and allow actions such as evacuate.

     .. warning::

        This must *only* be used if you have fully fenced the service in
        question, and that it can never send updates to the rest of the
        system. This can be done by powering off the node or completely
        isolating its networking. If you force-down a service that is not
        fenced you can corrupt the VMs that were running on that host.

-  **Hosts**

   Hosts are the *physical machines* that provide the resources for the virtual
   servers created in Nova. They run a **hypervisor** (see definition below)
   that handles the actual creation and management of the virtual servers.
   Hosts also run the **Nova compute service**, which receives requests from
   Nova to interact with the virtual servers on that machine. When compute
   service receives a request, it calls the appropriate methods of the driver
   for that hypervisor in order to carry out the request. The driver acts as
   the translator from generic Nova requests to hypervisor-specific calls.
   Hosts report their current state back to Nova, where it is tracked by the
   scheduler service, so that the scheduler can place requests for new virtual
   servers on the hosts that can best fit them.

-  **Host Actions**

   .. note::
     These APIs are deprecated in Microversion 2.43.

   A *host action* is one that affects the physical host machine, as opposed to
   actions that only affect the virtual servers running on that machine. There
   are three 'power' actions that are supported: *startup*, *shutdown*, and
   *reboot*. There are also two 'state' actions: enabling/disabling the host,
   and setting the host into or out of maintenance mode. Of course, carrying
   out these actions can affect running virtual servers on that host, so their
   state will need to be considered before carrying out the host action. For
   example, if you want to call the 'shutdown' action to turn off a host
   machine, you might want to migrate any virtual servers on that host before
   shutting down the host machine so that the virtual servers continue to be
   available without interruption.

-  **Hypervisors**

   A hypervisor, or virtual machine monitor (VMM), is a piece of computer
   software, firmware or hardware that creates and runs virtual machines.

   In nova, each Host (see `Hosts`) runs a hypervisor. Administrators are able
   to query the hypervisor for information, such as all the virtual servers
   currently running, as well as detailed info about the hypervisor, such as
   CPU, memory, or disk related configuration.

   Currently nova-compute also supports Ironic and LXC, but they don't have
   a hypervisor running.

-  **Aggregates**

   See :nova-doc:`Aggregates Developer Information <user/aggregates.html>`.

-  **Migrations**

   Migrations are the process where a virtual server is moved from one host to
   another. Please see :doc:`server_concepts` for details about
   moving servers.

   Administrators are able to query the records in database for information
   about migrations. For example, they can determine the source and
   destination hosts, type of migration, or changes in the server's flavor.
