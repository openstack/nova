=========================================
Select hosts where instances are launched
=========================================

With the appropriate permissions, you can select which host instances are
launched on and which roles can boot instances on this host.

Starting with the 2.74 microversion, there are two ways to specify a host
and/or node when creating a server.

Using Explicit Host and/or Node
-------------------------------

We can create servers by using explicit host and/or node. When we use this
way to request where instances are launched, we will still execute scheduler
filters on the requested destination.

.. todo: mention the minimum required release of python-openstackclient for
   the --host and --hypevisor-hostname options to work with "server create".

- To select the host where instances are launched, use the ``--host HOST``
  and/or ``--hypervisor-hostname HYPERVISOR`` options on
  the :command:`openstack server create` command.

  For example:

  .. code-block:: console

    $ openstack --os-compute-api-version 2.74 server create --image IMAGE \
    --flavor m1.tiny --key-name KEY --host HOST \
    --hypervisor-hostname HYPERVISOR --nic net-id=UUID SERVER

- To specify which roles can launch an instance on a specified host, enable
  the ``compute:servers:create:requested_destination`` rule in the
  ``policy.json`` file. By default, this rule is enabled for only the admin
  role. If you see ``Forbidden (HTTP 403)`` in the response, then you are
  not using the required credentials.

- To view the list of valid compute hosts and nodes, you can follow
  `Finding Host and Node Names`_.

[Legacy] Using Host and/or Node with Availability Zone
------------------------------------------------------

We can create servers by using host and/or node with availability zone. When
we use this way to select hosts where instances are launched, we will not run
the scheduler filters.

- To select the host where instances are launched, use the
  ``--availability-zone ZONE:HOST:NODE`` parameter on the :command:`openstack
  server create` command.

  For example:

  .. code-block:: console

    $ openstack server create --image IMAGE --flavor m1.tiny --key-name KEY \
    --availability-zone ZONE:HOST:NODE --nic net-id=UUID SERVER

  .. note::

    HOST and NODE are optional parameters. In such cases, use the
    ``--availability-zone ZONE::NODE``, ``--availability-zone ZONE:HOST`` or
    ``--availability-zone ZONE``.

- To specify which roles can launch an instance on a specified host, enable
  the ``os_compute_api:servers:create:forced_host`` rule in the ``policy.json``
  file. By default, this rule is enabled for only the admin role. If you see
  ``Forbidden (HTTP 403)`` in return, then you are not using the required
  credentials.

- To view the list of valid zones, use the :command:`openstack availability
  zone list --compute` command.

  .. code-block:: console

    $ openstack availability zone list --compute
    +-----------+-------------+
    | Zone Name | Zone Status |
    +-----------+-------------+
    | zone1     | available   |
    | zone2     | available   |
    +-----------+-------------+

- To view the list of valid compute hosts and nodes, you can follow
  `Finding Host and Node Names`_.

Finding Host and Node Names
---------------------------

- To view the list of valid compute hosts, use the :command:`openstack compute
  service list --service nova-compute` command.

  .. code-block:: console

    $ openstack compute service list --service nova-compute
    +----+--------------+---------------+------+---------+-------+----------------------------+
    | ID | Binary       | Host          | Zone | Status  | State | Updated At                 |
    +----+--------------+---------------+------+---------+-------+----------------------------+
    | 10 | nova-compute | compute01     | nova | enabled | up    | 2019-07-09T03:59:19.000000 |
    | 11 | nova-compute | compute02     | nova | enabled | up    | 2019-07-09T03:59:19.000000 |
    | 12 | nova-compute | compute03     | nova | enabled | up    | 2019-07-09T03:59:19.000000 |
    +----+--------------+---------------+------+---------+-------+----------------------------+

- To view the list of valid compute nodes, use the :command:`openstack
  hypervisor list` command.

  .. code-block:: console

    $ openstack hypervisor list
    +----+---------------------+-----------------+---------------+-------+
    | ID | Hypervisor Hostname | Hypervisor Type | Host IP       | State |
    +----+---------------------+-----------------+---------------+-------+
    |  6 | compute01           | QEMU            | 172.16.50.100 | up    |
    |  7 | compute02           | QEMU            | 172.16.50.101 | up    |
    |  8 | compute03           | QEMU            | 172.16.50.102 | up    |
    +----+---------------------+-----------------+---------------+-------+
