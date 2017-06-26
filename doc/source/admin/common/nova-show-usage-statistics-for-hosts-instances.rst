=============================================
Show usage statistics for hosts and instances
=============================================

You can show basic statistics on resource usage for hosts and instances.

.. note::

   For more sophisticated monitoring, see the
   `ceilometer <https://launchpad.net/ceilometer>`__ project. You can
   also use tools, such as `Ganglia <http://ganglia.info/>`__ or
   `Graphite <http://graphite.wikidot.com/>`__, to gather more detailed
   data.

Show host usage statistics
~~~~~~~~~~~~~~~~~~~~~~~~~~

The following examples show the host usage statistics for a host called
``devstack``.

* List the hosts and the nova-related services that run on them:

  .. code-block:: console

     $ openstack host list
     +-----------+-------------+----------+
     | Host Name | Service     | Zone     |
     +-----------+-------------+----------+
     | devstack  | conductor   | internal |
     | devstack  | compute     | nova     |
     | devstack  | cert        | internal |
     | devstack  | network     | internal |
     | devstack  | scheduler   | internal |
     | devstack  | consoleauth | internal |
     +-----------+-------------+----------+

* Get a summary of resource usage of all of the instances running on the host:

  .. code-block:: console

     $ openstack host show devstack
     +----------+----------------------------------+-----+-----------+---------+
     | Host     | Project                          | CPU | MEMORY MB | DISK GB |
     +----------+----------------------------------+-----+-----------+---------+
     | devstack | (total)                          | 2   | 4003      | 157     |
     | devstack | (used_now)                       | 3   | 5120      | 40      |
     | devstack | (used_max)                       | 3   | 4608      | 40      |
     | devstack | b70d90d65e464582b6b2161cf3603ced | 1   | 512       | 0       |
     | devstack | 66265572db174a7aa66eba661f58eb9e | 2   | 4096      | 40      |
     +----------+----------------------------------+-----+-----------+---------+

  The ``CPU`` column shows the sum of the virtual CPUs for instances running on
  the host.

  The ``MEMORY MB`` column shows the sum of the memory (in MB) allocated to the
  instances that run on the host.

  The ``DISK GB`` column shows the sum of the root and ephemeral disk sizes (in
  GB) of the instances that run on the host.

  The row that has the value ``used_now`` in the ``PROJECT`` column shows the
  sum of the resources allocated to the instances that run on the host, plus
  the resources allocated to the virtual machine of the host itself.

  The row that has the value ``used_max`` in the ``PROJECT`` column shows the
  sum of the resources allocated to the instances that run on the host.

  .. note::

     These values are computed by using information about the flavors of the
     instances that run on the hosts. This command does not query the CPU
     usage, memory usage, or hard disk usage of the physical host.

Show instance usage statistics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Get CPU, memory, I/O, and network statistics for an instance.

  #. List instances:

     .. code-block:: console

        $ openstack server list
        +----------+----------------------+--------+------------+-------------+------------------+------------+
        | ID       | Name                 | Status | Task State | Power State | Networks         | Image Name |
        +----------+----------------------+--------+------------+-------------+------------------+------------+
        | 84c6e... | myCirrosServer       | ACTIVE | None       | Running     | private=10.0.0.3 | cirros     |
        | 8a995... | myInstanceFromVolume | ACTIVE | None       | Running     | private=10.0.0.4 | ubuntu     |
        +----------+----------------------+--------+------------+-------------+------------------+------------+

  #. Get diagnostic statistics:

     .. code-block:: console

        $ nova diagnostics myCirrosServer
        +---------------------------+--------+
        | Property                  | Value  |
        +---------------------------+--------+
        | memory                    | 524288 |
        | memory-actual             | 524288 |
        | memory-rss                | 6444   |
        | tap1fec8fb8-7a_rx         | 22137  |
        | tap1fec8fb8-7a_rx_drop    | 0      |
        | tap1fec8fb8-7a_rx_errors  | 0      |
        | tap1fec8fb8-7a_rx_packets | 166    |
        | tap1fec8fb8-7a_tx         | 18032  |
        | tap1fec8fb8-7a_tx_drop    | 0      |
        | tap1fec8fb8-7a_tx_errors  | 0      |
        | tap1fec8fb8-7a_tx_packets | 130    |
        | vda_errors                | -1     |
        | vda_read                  | 2048   |
        | vda_read_req              | 2      |
        | vda_write                 | 182272 |
        | vda_write_req             | 74     |
        +---------------------------+--------+

* Get summary statistics for each project:

  .. code-block:: console

     $ openstack usage list
     Usage from 2013-06-25 to 2013-07-24:
     +---------+---------+--------------+-----------+---------------+
     | Project | Servers | RAM MB-Hours | CPU Hours | Disk GB-Hours |
     +---------+---------+--------------+-----------+---------------+
     | demo    | 1       | 344064.44    | 672.00    | 0.00          |
     | stack   | 3       | 671626.76    | 327.94    | 6558.86       |
     +---------+---------+--------------+-----------+---------------+
