=========================================
Select hosts where instances are launched
=========================================

With the appropriate permissions, you can select which host instances are
launched on and which roles can boot instances on this host.

#. To select the host where instances are launched, use the
   ``--availability-zone ZONE:HOST:NODE`` parameter on the :command:`openstack
   server create` command.

   For example:

   .. code-block:: console

      $ openstack server create --image IMAGE --flavor m1.tiny \
        --key-name KEY --availability-zone ZONE:HOST:NODE \
        --nic net-id=UUID SERVER

   .. note::

      HOST and NODE are optional parameters. In such cases, use the
      ``--availability-zone ZONE::NODE``, ``--availability-zone ZONE:HOST`` or
      ``--availability-zone ZONE``.

#. To specify which roles can launch an instance on a specified host, enable
   the ``create:forced_host`` option in the ``policy.json`` file. By default,
   this option is enabled for only the admin role. If you see ``Forbidden (HTTP
   403)`` in return, then you are not using admin credentials.

#. To view the list of valid zones, use the :command:`openstack availability
   zone list` command.

   .. code-block:: console

      $ openstack availability zone list
      +-----------+-------------+
      | Zone Name | Zone Status |
      +-----------+-------------+
      | zone1     | available   |
      | zone2     | available   |
      +-----------+-------------+

#. To view the list of valid compute hosts, use the :command:`openstack host
   list` command.

   .. code-block:: console

      $ openstack host list
      +----------------+-------------+----------+
      | Host Name      | Service     | Zone     |
      +----------------+-------------+----------+
      | compute01      | compute     | nova     |
      | compute02      | compute     | nova     |
      +----------------+-------------+----------+


#. To view the list of valid compute nodes, use the :command:`openstack
   hypervisor list` command.

   .. code-block:: console

      $ openstack hypervisor list
      +----+---------------------+
      | ID | Hypervisor Hostname |
      +----+---------------------+
      |  1 | server2             |
      |  2 | server3             |
      |  3 | server4             |
      +----+---------------------+
