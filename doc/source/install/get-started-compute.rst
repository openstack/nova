========================
Compute service overview
========================

.. todo:: Update a lot of the links in here.

Use OpenStack Compute to host and manage cloud computing systems.  OpenStack
Compute is a major part of an Infrastructure-as-a-Service (IaaS) system. The
main modules are implemented in Python.

OpenStack Compute interacts with OpenStack Identity for authentication,
OpenStack Placement for resource inventory tracking and selection, OpenStack
Image service for disk and server images, and OpenStack Dashboard for the user
and administrative interface. Image access is limited by projects, and by
users; quotas are limited per project (the number of instances, for example).
OpenStack Compute can scale horizontally on standard hardware, and download
images to launch instances.

OpenStack Compute consists of the following areas and their components:

``nova-api`` service
  Accepts and responds to end user compute API calls. The service supports the
  OpenStack Compute API.  It enforces some policies and initiates most
  orchestration activities, such as running an instance.

``nova-api-metadata`` service
  Accepts metadata requests from instances. For more information, refer to
  :doc:`/admin/metadata-service`.

``nova-compute`` service
  A worker daemon that creates and terminates virtual machine instances through
  hypervisor APIs. For example:

  - XenAPI for XenServer/XCP

  - libvirt for KVM or QEMU

  - VMwareAPI for VMware

  Processing is fairly complex. Basically, the daemon accepts actions from the
  queue and performs a series of system commands such as launching a KVM
  instance and updating its state in the database.

``nova-scheduler`` service
  Takes a virtual machine instance request from the queue and determines on
  which compute server host it runs.

``nova-conductor`` module
  Mediates interactions between the ``nova-compute`` service and the database.
  It eliminates direct accesses to the cloud database made by the
  ``nova-compute`` service. The ``nova-conductor`` module scales horizontally.
  However, do not deploy it on nodes where the ``nova-compute`` service runs.
  For more information, see the ``conductor`` section in the
  :doc:`/configuration/config`.

``nova-novncproxy`` daemon
  Provides a proxy for accessing running instances through a VNC connection.
  Supports browser-based novnc clients.

``nova-spicehtml5proxy`` daemon
  Provides a proxy for accessing running instances through a SPICE connection.
  Supports browser-based HTML5 client.

The queue
  A central hub for passing messages between daemons. Usually implemented with
  `RabbitMQ <https://www.rabbitmq.com/>`__ but
  :oslo.messaging-doc:`other options are available <admin/drivers>`.

SQL database
  Stores most build-time and run-time states for a cloud infrastructure,
  including:

  -  Available instance types

  -  Instances in use

  -  Available networks

  -  Projects

  Theoretically, OpenStack Compute can support any database that SQLAlchemy
  supports. Common databases are SQLite3 for test and development work, MySQL,
  MariaDB, and PostgreSQL.
