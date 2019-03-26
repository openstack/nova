=======================
Manage Compute services
=======================

You can enable and disable Compute services. The following examples disable and
enable the ``nova-compute`` service.

#. List the Compute services:

   .. code-block:: console

      $ openstack compute service list
      +----+--------------+------------+----------+---------+-------+--------------+
      | ID | Binary       | Host       | Zone     | Status  | State | Updated At   |
      +----+--------------+------------+----------+---------+-------+--------------+
      |  4 | nova-        | controller | internal | enabled | up    | 2016-12-20T0 |
      |    | consoleauth  |            |          |         |       | 0:44:48.0000 |
      |    |              |            |          |         |       | 00           |
      |  5 | nova-        | controller | internal | enabled | up    | 2016-12-20T0 |
      |    | scheduler    |            |          |         |       | 0:44:48.0000 |
      |    |              |            |          |         |       | 00           |
      |  6 | nova-        | controller | internal | enabled | up    | 2016-12-20T0 |
      |    | conductor    |            |          |         |       | 0:44:54.0000 |
      |    |              |            |          |         |       | 00           |
      |  9 | nova-compute | compute    | nova     | enabled | up    | 2016-10-21T0 |
      |    |              |            |          |         |       | 2:35:03.0000 |
      |    |              |            |          |         |       | 00           |
      +----+--------------+------------+----------+---------+-------+--------------+

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
      +----+--------------+------------+----------+---------+-------+--------------+
      | ID | Binary       | Host       | Zone     | Status  | State | Updated At   |
      +----+--------------+------------+----------+---------+-------+--------------+
      |  4 | nova-        | controller | internal | enabled | up    | 2016-12-20T0 |
      |    | consoleauth  |            |          |         |       | 0:44:48.0000 |
      |    |              |            |          |         |       | 00           |
      |  5 | nova-        | controller | internal | enabled | up    | 2016-12-20T0 |
      |    | scheduler    |            |          |         |       | 0:44:48.0000 |
      |    |              |            |          |         |       | 00           |
      |  6 | nova-        | controller | internal | enabled | up    | 2016-12-20T0 |
      |    | conductor    |            |          |         |       | 0:44:54.0000 |
      |    |              |            |          |         |       | 00           |
      |  9 | nova-compute | compute    | nova     | disabled| up    | 2016-10-21T0 |
      |    |              |            |          |         |       | 2:35:03.0000 |
      |    |              |            |          |         |       | 00           |
      +----+--------------+------------+----------+---------+-------+--------------+

#. Enable the service:

   .. code-block:: console

      $ openstack compute service set --enable compute nova-compute
      +----------+--------------+---------+
      | Host     | Binary       | Status  |
      +----------+--------------+---------+
      | compute  | nova-compute | enabled |
      +----------+--------------+---------+
