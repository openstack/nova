=======================
Manage Compute services
=======================

You can enable and disable Compute services. The following examples disable and
enable the ``nova-compute`` service.

#. List the Compute services:

   .. code-block:: console

      $ openstack compute service list
      +----+----------------+------------+----------+---------+-------+----------------------------+
      | ID | Binary         | Host       | Zone     | Status  | State | Updated At                 |
      +----+----------------+------------+----------+---------+-------+----------------------------+
      |  4 | nova-scheduler | controller | internal | enabled | up    | 2016-12-20T00:44:48.000000 |
      |  5 | nova-conductor | controller | internal | enabled | up    | 2016-12-20T00:44:54.000000 |
      |  8 | nova-compute   | compute    | nova     | enabled | up    | 2016-10-21T02:35:03.000000 |
      +----+----------------+------------+----------+---------+-------+----------------------------+

#. Disable a nova service:

   .. code-block:: console

      $ openstack compute service set --disable --disable-reason "trial log" compute nova-compute
      +----------+--------------+----------+-------------------+
      | Host     | Binary       | Status   | Disabled Reason   |
      +----------+--------------+----------+-------------------+
      | compute  | nova-compute | disabled | trial log         |
      +----------+--------------+----------+-------------------+

#. Check the service list:

   .. code-block:: console

      $ openstack compute service list
      +----+----------------+------------+----------+---------+-------+----------------------------+
      | ID | Binary         | Host       | Zone     | Status  | State | Updated At                 |
      +----+----------------+------------+----------+---------+-------+----------------------------+
      |  5 | nova-scheduler | controller | internal | enabled | up    | 2016-12-20T00:44:48.000000 |
      |  6 | nova-conductor | controller | internal | enabled | up    | 2016-12-20T00:44:54.000000 |
      |  9 | nova-compute   | compute    | nova     | disabled| up    | 2016-10-21T02:35:03.000000 |
      +----+----------------+------------+----------+---------+-------+----------------------------+

#. Enable the service:

   .. code-block:: console

      $ openstack compute service set --enable compute nova-compute
      +----------+--------------+---------+
      | Host     | Binary       | Status  |
      +----------+--------------+---------+
      | compute  | nova-compute | enabled |
      +----------+--------------+---------+
