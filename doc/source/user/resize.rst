==============================
Change the size of your server
==============================

Change the size of a server by changing its flavor.

#. Show information about your server, including its size, which is shown
   as the value of the flavor property:

   .. code-block:: console

      $ openstack server show myCirrosServer
      +--------------------------------------+----------------------------------------------------------+
      | Field                                | Value                                                    |
      +--------------------------------------+----------------------------------------------------------+
      | OS-DCF:diskConfig                    | AUTO                                                     |
      | OS-EXT-AZ:availability_zone          | nova                                                     |
      | OS-EXT-SRV-ATTR:host                 | node-7.domain.tld                                        |
      | OS-EXT-SRV-ATTR:hypervisor_hostname  | node-7.domain.tld                                        |
      | OS-EXT-SRV-ATTR:instance_name        | instance-000000f3                                        |
      | OS-EXT-STS:power_state               | 1                                                        |
      | OS-EXT-STS:task_state                | None                                                     |
      | OS-EXT-STS:vm_state                  | active                                                   |
      | OS-SRV-USG:launched_at               | 2016-10-26T01:13:15.000000                               |
      | OS-SRV-USG:terminated_at             | None                                                     |
      | accessIPv4                           |                                                          |
      | accessIPv6                           |                                                          |
      | addresses                            | admin_internal_net=192.168.111.139                       |
      | config_drive                         | True                                                     |
      | created                              | 2016-10-26T01:12:38Z                                     |
      | flavor                               | m1.small (2)                                             |
      | hostId                               | d815539ce1a8fad3d597c3438c13f1229d3a2ed66d1a75447845a2f3 |
      | id                                   | 67bc9a9a-5928-47c4-852c-3631fef2a7e8                     |
      | image                                | cirros-test (dc5ec4b8-5851-4be8-98aa-df7a9b8f538f)       |
      | key_name                             | None                                                     |
      | name                                 | myCirrosServer                                           |
      | os-extended-volumes:volumes_attached | []                                                       |
      | progress                             | 0                                                        |
      | project_id                           | c08367f25666480f9860c6a0122dfcc4                         |
      | properties                           |                                                          |
      | security_groups                      | [{u'name': u'default'}]                                  |
      | status                               | ACTIVE                                                   |
      | updated                              | 2016-10-26T01:13:00Z                                     |
      | user_id                              | 0209430e30924bf9b5d8869990234e44                         |
      +--------------------------------------+----------------------------------------------------------+

   The size (flavor) of the server is ``m1.small (2)``.

#. List the available flavors with the following command:

   .. code-block:: console

      $ openstack flavor list
      +-----+-----------+-------+------+-----------+-------+-----------+
      | ID  | Name      |   RAM | Disk | Ephemeral | VCPUs | Is_Public |
      +-----+-----------+-------+------+-----------+-------+-----------+
      | 1   | m1.tiny   |   512 |    1 |         0 |     1 | True      |
      | 2   | m1.small  |  2048 |   20 |         0 |     1 | True      |
      | 3   | m1.medium |  4096 |   40 |         0 |     2 | True      |
      | 4   | m1.large  |  8192 |   80 |         0 |     4 | True      |
      | 5   | m1.xlarge | 16384 |  160 |         0 |     8 | True      |
      +-----+-----------+-------+------+-----------+-------+-----------+

#. To resize the server, use the :command:`openstack server resize` command and
   add the server ID or name and the new flavor. For example:

   .. code-block:: console

      $ openstack server resize --flavor 4 myCirrosServer


   .. note::

      By default, the :command:`openstack server resize` command gives
      the guest operating
      system a chance to perform a controlled shutdown before the instance
      is powered off and the instance is resized.
      The shutdown behavior is configured by the
      :oslo.config:option:`shutdown_timeout` parameter that can be set in the
      ``nova.conf`` file. Its value stands for the overall
      period (in seconds) a guest operating system is allowed
      to complete the shutdown. The default timeout is 60 seconds.

      The timeout value can be overridden on a per image basis
      by means of ``os_shutdown_timeout`` that is an image metadata
      setting allowing different types of operating systems to specify
      how much time they need to shut down cleanly. See
      :glance-doc:`Useful image properties <admin/useful-image-properties>`
      for details.

#. Show the status for your server.

   .. code-block:: console

      $ openstack server list
      +----------------------+----------------+--------+-----------------------------------------+
      | ID                   | Name           | Status | Networks                                |
      +----------------------+----------------+--------+-----------------------------------------+
      | 67bc9a9a-5928-47c... | myCirrosServer | RESIZE | admin_internal_net=192.168.111.139      |
      +----------------------+----------------+--------+-----------------------------------------+

   When the resize completes, the status becomes ``VERIFY_RESIZE``.

#. Confirm the resize. For example:

   .. code-block:: console

      $ openstack server resize --confirm 67bc9a9a-5928-47c4-852c-3631fef2a7e8

   The server status becomes ``ACTIVE``.

#. If the resize fails or does not work as expected, you can revert the
   resize. For example:

   .. code-block:: console

      $ openstack server resize --revert 67bc9a9a-5928-47c4-852c-3631fef2a7e8

   The server status becomes ``ACTIVE``.
