Install and configure controller node for Red Hat Enterprise Linux and CentOS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to install and configure the Compute service,
code-named nova, on the controller node.

Prerequisites
-------------

Before you install and configure the Compute service, you must create
databases, service credentials, and API endpoints.

#. To create the databases, complete these steps:

   * Use the database access client to connect to the database server
     as the ``root`` user:

     .. code-block:: console

        $ mysql -u root -p

   * Create the ``nova_api``, ``nova``, ``nova_cell0``, and ``placement`` databases:

     .. code-block:: console

        MariaDB [(none)]> CREATE DATABASE nova_api;
        MariaDB [(none)]> CREATE DATABASE nova;
        MariaDB [(none)]> CREATE DATABASE nova_cell0;
        MariaDB [(none)]> CREATE DATABASE placement;

   * Grant proper access to the databases:

     .. code-block:: console

        MariaDB [(none)]> GRANT ALL PRIVILEGES ON nova_api.* TO 'nova'@'localhost' \
          IDENTIFIED BY 'NOVA_DBPASS';
        MariaDB [(none)]> GRANT ALL PRIVILEGES ON nova_api.* TO 'nova'@'%' \
          IDENTIFIED BY 'NOVA_DBPASS';

        MariaDB [(none)]> GRANT ALL PRIVILEGES ON nova.* TO 'nova'@'localhost' \
          IDENTIFIED BY 'NOVA_DBPASS';
        MariaDB [(none)]> GRANT ALL PRIVILEGES ON nova.* TO 'nova'@'%' \
          IDENTIFIED BY 'NOVA_DBPASS';

        MariaDB [(none)]> GRANT ALL PRIVILEGES ON nova_cell0.* TO 'nova'@'localhost' \
          IDENTIFIED BY 'NOVA_DBPASS';
        MariaDB [(none)]> GRANT ALL PRIVILEGES ON nova_cell0.* TO 'nova'@'%' \
          IDENTIFIED BY 'NOVA_DBPASS';

        MariaDB [(none)]> GRANT ALL PRIVILEGES ON placement.* TO 'placement'@'localhost' \
          IDENTIFIED BY 'PLACEMENT_DBPASS';
        MariaDB [(none)]> GRANT ALL PRIVILEGES ON placement.* TO 'placement'@'%' \
          IDENTIFIED BY 'PLACEMENT_DBPASS';

     Replace ``NOVA_DBPASS`` and ``PLACEMENT_DBPASS`` with a suitable password.

   * Exit the database access client.

#. Source the ``admin`` credentials to gain access to admin-only CLI commands:

   .. code-block:: console

      $ . admin-openrc

#. Create the Compute service credentials:

   * Create the ``nova`` user:

     .. code-block:: console

        $ openstack user create --domain default --password-prompt nova

        User Password:
        Repeat User Password:
        +---------------------+----------------------------------+
        | Field               | Value                            |
        +---------------------+----------------------------------+
        | domain_id           | default                          |
        | enabled             | True                             |
        | id                  | 8a7dbf5279404537b1c7b86c033620fe |
        | name                | nova                             |
        | options             | {}                               |
        | password_expires_at | None                             |
        +---------------------+----------------------------------+

   * Add the ``admin`` role to the ``nova`` user:

     .. code-block:: console

        $ openstack role add --project service --user nova admin

     .. note::

        This command provides no output.

   * Create the ``nova`` service entity:

     .. code-block:: console

        $ openstack service create --name nova \
          --description "OpenStack Compute" compute

        +-------------+----------------------------------+
        | Field       | Value                            |
        +-------------+----------------------------------+
        | description | OpenStack Compute                |
        | enabled     | True                             |
        | id          | 060d59eac51b4594815603d75a00aba2 |
        | name        | nova                             |
        | type        | compute                          |
        +-------------+----------------------------------+

#. Create the Compute API service endpoints:

   .. code-block:: console

      $ openstack endpoint create --region RegionOne \
        compute public http://controller:8774/v2.1

      +--------------+-------------------------------------------+
      | Field        | Value                                     |
      +--------------+-------------------------------------------+
      | enabled      | True                                      |
      | id           | 3c1caa473bfe4390a11e7177894bcc7b          |
      | interface    | public                                    |
      | region       | RegionOne                                 |
      | region_id    | RegionOne                                 |
      | service_id   | 060d59eac51b4594815603d75a00aba2          |
      | service_name | nova                                      |
      | service_type | compute                                   |
      | url          | http://controller:8774/v2.1               |
      +--------------+-------------------------------------------+

      $ openstack endpoint create --region RegionOne \
        compute internal http://controller:8774/v2.1

      +--------------+-------------------------------------------+
      | Field        | Value                                     |
      +--------------+-------------------------------------------+
      | enabled      | True                                      |
      | id           | e3c918de680746a586eac1f2d9bc10ab          |
      | interface    | internal                                  |
      | region       | RegionOne                                 |
      | region_id    | RegionOne                                 |
      | service_id   | 060d59eac51b4594815603d75a00aba2          |
      | service_name | nova                                      |
      | service_type | compute                                   |
      | url          | http://controller:8774/v2.1               |
      +--------------+-------------------------------------------+

      $ openstack endpoint create --region RegionOne \
        compute admin http://controller:8774/v2.1

      +--------------+-------------------------------------------+
      | Field        | Value                                     |
      +--------------+-------------------------------------------+
      | enabled      | True                                      |
      | id           | 38f7af91666a47cfb97b4dc790b94424          |
      | interface    | admin                                     |
      | region       | RegionOne                                 |
      | region_id    | RegionOne                                 |
      | service_id   | 060d59eac51b4594815603d75a00aba2          |
      | service_name | nova                                      |
      | service_type | compute                                   |
      | url          | http://controller:8774/v2.1               |
      +--------------+-------------------------------------------+

#. Create a Placement service user using your chosen ``PLACEMENT_PASS``:

   .. code-block:: console

      $ openstack user create --domain default --password-prompt placement

      User Password:
      Repeat User Password:
      +---------------------+----------------------------------+
      | Field               | Value                            |
      +---------------------+----------------------------------+
      | domain_id           | default                          |
      | enabled             | True                             |
      | id                  | fa742015a6494a949f67629884fc7ec8 |
      | name                | placement                        |
      | options             | {}                               |
      | password_expires_at | None                             |
      +---------------------+----------------------------------+

#. Add the Placement user to the service project with the admin role:

   .. code-block:: console

      $ openstack role add --project service --user placement admin

   .. note::

      This command provides no output.

#. Create the Placement API entry in the service catalog:

   .. code-block:: console

      $ openstack service create --name placement \
        --description "Placement API" placement

      +-------------+----------------------------------+
      | Field       | Value                            |
      +-------------+----------------------------------+
      | description | Placement API                    |
      | enabled     | True                             |
      | id          | 2d1a27022e6e4185b86adac4444c495f |
      | name        | placement                        |
      | type        | placement                        |
      +-------------+----------------------------------+

#. Create the Placement API service endpoints:

   .. code-block:: console

      $ openstack endpoint create --region RegionOne \
        placement public http://controller:8778

      +--------------+----------------------------------+
      | Field        | Value                            |
      +--------------+----------------------------------+
      | enabled      | True                             |
      | id           | 2b1b2637908b4137a9c2e0470487cbc0 |
      | interface    | public                           |
      | region       | RegionOne                        |
      | region_id    | RegionOne                        |
      | service_id   | 2d1a27022e6e4185b86adac4444c495f |
      | service_name | placement                        |
      | service_type | placement                        |
      | url          | http://controller:8778           |
      +--------------+----------------------------------+

      $ openstack endpoint create --region RegionOne \
        placement internal http://controller:8778

      +--------------+----------------------------------+
      | Field        | Value                            |
      +--------------+----------------------------------+
      | enabled      | True                             |
      | id           | 02bcda9a150a4bd7993ff4879df971ab |
      | interface    | internal                         |
      | region       | RegionOne                        |
      | region_id    | RegionOne                        |
      | service_id   | 2d1a27022e6e4185b86adac4444c495f |
      | service_name | placement                        |
      | service_type | placement                        |
      | url          | http://controller:8778           |
      +--------------+----------------------------------+

      $ openstack endpoint create --region RegionOne \
        placement admin http://controller:8778

      +--------------+----------------------------------+
      | Field        | Value                            |
      +--------------+----------------------------------+
      | enabled      | True                             |
      | id           | 3d71177b9e0f406f98cbff198d74b182 |
      | interface    | admin                            |
      | region       | RegionOne                        |
      | region_id    | RegionOne                        |
      | service_id   | 2d1a27022e6e4185b86adac4444c495f |
      | service_name | placement                        |
      | service_type | placement                        |
      | url          | http://controller:8778           |
      +--------------+----------------------------------+

Install and configure components
--------------------------------

.. include:: shared/note_configuration_vary_by_distribution.rst

#. Install the packages:

   .. code-block:: console

      # yum install openstack-nova-api openstack-nova-conductor \
        openstack-nova-console openstack-nova-novncproxy \
        openstack-nova-scheduler openstack-nova-placement-api

#. Edit the ``/etc/nova/nova.conf`` file and complete the following actions:

   * In the ``[DEFAULT]`` section, enable only the compute and metadata APIs:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        enabled_apis = osapi_compute,metadata

   * In the ``[api_database]``, ``[database]``, and ``[placement_database]``
     sections, configure database access:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [api_database]
        # ...
        connection = mysql+pymysql://nova:NOVA_DBPASS@controller/nova_api

        [database]
        # ...
        connection = mysql+pymysql://nova:NOVA_DBPASS@controller/nova

        [placement_database]
        # ...
        connection = mysql+pymysql://placement:PLACEMENT_DBPASS@controller/placement

     Replace ``NOVA_DBPASS`` with the password you chose for the Compute
     databases and ``PLACEMENT_DBPASS`` for Placement database.

   * In the ``[DEFAULT]`` section, configure ``RabbitMQ`` message queue access:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        transport_url = rabbit://openstack:RABBIT_PASS@controller

     Replace ``RABBIT_PASS`` with the password you chose for the ``openstack``
     account in ``RabbitMQ``.

   * In the ``[api]`` and ``[keystone_authtoken]`` sections, configure Identity
     service access:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [api]
        # ...
        auth_strategy = keystone

        [keystone_authtoken]
        # ...
        auth_url = http://controller:5000/v3
        memcached_servers = controller:11211
        auth_type = password
        project_domain_name = default
        user_domain_name = default
        project_name = service
        username = nova
        password = NOVA_PASS

     Replace ``NOVA_PASS`` with the password you chose for the ``nova`` user in
     the Identity service.

     .. note::

        Comment out or remove any other options in the ``[keystone_authtoken]``
        section.

   * In the ``[DEFAULT]`` section, configure the ``my_ip`` option to use the
     management interface IP address of the controller node:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        my_ip = 10.0.0.11

   * In the ``[DEFAULT]`` section, enable support for the Networking service:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        use_neutron = true
        firewall_driver = nova.virt.firewall.NoopFirewallDriver

     .. note::

        By default, Compute uses an internal firewall driver. Since the
        Networking service includes a firewall driver, you must disable the
        Compute firewall driver by using the
        ``nova.virt.firewall.NoopFirewallDriver`` firewall driver.

   * Configure the ``[neutron]`` section of **/etc/nova/nova.conf**. Refer to
     the :neutron-doc:`Networking service install guide
     <install/compute-install-rdo.html>` for more details.

   * In the ``[vnc]`` section, configure the VNC proxy to use the management
     interface IP address of the controller node:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [vnc]
        enabled = true
        # ...
        server_listen = $my_ip
        server_proxyclient_address = $my_ip

   * In the ``[glance]`` section, configure the location of the Image service
     API:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [glance]
        # ...
        api_servers = http://controller:9292

   * In the ``[oslo_concurrency]`` section, configure the lock path:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [oslo_concurrency]
        # ...
        lock_path = /var/lib/nova/tmp

   *  In the ``[placement]`` section, configure the Placement API:

      .. path /etc/nova/nova.conf
      .. code-block:: ini

         [placement]
         # ...
         region_name = RegionOne
         project_domain_name = Default
         project_name = service
         auth_type = password
         user_domain_name = Default
         auth_url = http://controller:5000/v3
         username = placement
         password = PLACEMENT_PASS

      Replace ``PLACEMENT_PASS`` with the password you choose for the
      ``placement`` user in the Identity service. Comment out any other options
      in the ``[placement]`` section.

   * Due to a `packaging bug
     <https://bugzilla.redhat.com/show_bug.cgi?id=1430540>`_, you must enable
     access to the Placement API by adding the following configuration to
     ``/etc/httpd/conf.d/00-nova-placement-api.conf``:

     .. path /etc/httpd/conf.d/00-nova-placement-api.conf
     .. code-block:: ini

        <Directory /usr/bin>
           <IfVersion >= 2.4>
              Require all granted
           </IfVersion>
           <IfVersion < 2.4>
              Order allow,deny
              Allow from all
           </IfVersion>
        </Directory>

   * Restart the httpd service:

     .. code-block:: console

        # systemctl restart httpd

#. Populate the ``nova-api`` and ``placement`` databases:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage api_db sync" nova

   .. note::

      Ignore any deprecation messages in this output.

#. Register the ``cell0`` database:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage cell_v2 map_cell0" nova

#. Create the ``cell1`` cell:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage cell_v2 create_cell --name=cell1 --verbose" nova
      109e1d4b-536a-40d0-83c6-5f121b82b650

#. Populate the nova database:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage db sync" nova

#. Verify nova cell0 and cell1 are registered correctly:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage cell_v2 list_cells" nova
      +-------+--------------------------------------+
      | Name  | UUID                                 |
      +-------+--------------------------------------+
      | cell1 | 109e1d4b-536a-40d0-83c6-5f121b82b650 |
      | cell0 | 00000000-0000-0000-0000-000000000000 |
      +-------+--------------------------------------+

Finalize installation
---------------------

* Start the Compute services and configure them to start when the system boots:

  .. note:: ``nova-consoleauth`` is deprecated since 18.0.0 (Rocky) and will
            be removed in an upcoming release. Console proxies should be
            deployed per cell. If performing a fresh install (not an upgrade),
            then you likely do not need to install the ``nova-consoleauth``
            service. See
            :oslo.config:option:`workarounds.enable_consoleauth` for details.

  .. code-block:: console

     # systemctl enable openstack-nova-api.service \
       openstack-nova-consoleauth openstack-nova-scheduler.service \
       openstack-nova-conductor.service openstack-nova-novncproxy.service
     # systemctl start openstack-nova-api.service \
       openstack-nova-consoleauth openstack-nova-scheduler.service \
       openstack-nova-conductor.service openstack-nova-novncproxy.service
