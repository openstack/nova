Install and configure controller node for Ubuntu
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

        # mysql

   * Create the ``nova_api``, ``nova``, and ``nova_cell0`` databases:

     .. code-block:: console

        MariaDB [(none)]> CREATE DATABASE nova_api;
        MariaDB [(none)]> CREATE DATABASE nova;
        MariaDB [(none)]> CREATE DATABASE nova_cell0;

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

     Replace ``NOVA_DBPASS`` with a suitable password.

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

Install and configure components
--------------------------------

.. include:: shared/note_configuration_vary_by_distribution.rst

#. Install the packages:

   .. code-block:: console

      # apt install nova-api nova-conductor nova-novncproxy nova-scheduler

#. Edit the ``/etc/nova/nova.conf`` file and complete the following actions:

   * In the ``[api_database]`` and ``[database]`` sections, configure database
     access:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [api_database]
        # ...
        connection = mysql+pymysql://nova:NOVA_DBPASS@controller/nova_api

        [database]
        # ...
        connection = mysql+pymysql://nova:NOVA_DBPASS@controller/nova

     Replace ``NOVA_DBPASS`` with the password you chose for the Compute
     databases.

   * In the ``[DEFAULT]`` section, configure ``RabbitMQ`` message queue access:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        transport_url = rabbit://openstack:RABBIT_PASS@controller:5672/

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
        www_authenticate_uri = http://controller:5000/
        auth_url = http://controller:5000/
        memcached_servers = controller:11211
        auth_type = password
        project_domain_name = Default
        user_domain_name = Default
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
     <install/controller-install-ubuntu.html#configure-the-compute-service-to-use-the-networking-service>`
     for more information.

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

   * Due to a packaging bug, remove the ``log_dir`` option from the
     ``[DEFAULT]`` section.

   *  In the ``[placement]`` section, configure access to the Placement
      service:

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
      ``placement`` service user created when installing
      :placement-doc:`Placement <install/>`. Comment out or remove any other
      options in the ``[placement]`` section.

#. Populate the ``nova-api`` database:

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

#. Populate the nova database:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage db sync" nova

#. Verify nova cell0 and cell1 are registered correctly:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage cell_v2 list_cells" nova
      +-------+--------------------------------------+----------------------------------------------------+--------------------------------------------------------------+----------+
      |  Name |                 UUID                 |                   Transport URL                    |                     Database Connection                      | Disabled |
      +-------+--------------------------------------+----------------------------------------------------+--------------------------------------------------------------+----------+
      | cell0 | 00000000-0000-0000-0000-000000000000 |                       none:/                       | mysql+pymysql://nova:****@controller/nova_cell0?charset=utf8 |  False   |
      | cell1 | f690f4fd-2bc5-4f15-8145-db561a7b9d3d | rabbit://openstack:****@controller:5672/nova_cell1 | mysql+pymysql://nova:****@controller/nova_cell1?charset=utf8 |  False   |
      +-------+--------------------------------------+----------------------------------------------------+--------------------------------------------------------------+----------+

Finalize installation
---------------------

* Restart the Compute services:

  .. code-block:: console

     # service nova-api restart
     # service nova-scheduler restart
     # service nova-conductor restart
     # service nova-novncproxy restart
