Install and configure a compute node for Red Hat Enterprise Linux and CentOS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to install and configure the Compute service on a
compute node. The service supports several hypervisors to deploy instances or
virtual machines (VMs). For simplicity, this configuration uses the Quick
EMUlator (QEMU) hypervisor with the kernel-based VM (KVM) extension on compute
nodes that support hardware acceleration for virtual machines. On legacy
hardware, this configuration uses the generic QEMU hypervisor. You can follow
these instructions with minor modifications to horizontally scale your
environment with additional compute nodes.

.. note::

   This section assumes that you are following the instructions in this guide
   step-by-step to configure the first compute node. If you want to configure
   additional compute nodes, prepare them in a similar fashion to the first
   compute node in the :ref:`example architectures
   <overview-example-architectures>` section. Each additional compute node
   requires a unique IP address.

Install and configure components
--------------------------------

.. include:: shared/note_configuration_vary_by_distribution.rst

#. Install the packages:

   .. code-block:: console

      # yum install openstack-nova-compute

#. Edit the ``/etc/nova/nova.conf`` file and complete the following actions:

   * In the ``[DEFAULT]`` section, enable only the compute and
     metadata APIs:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        enabled_apis = osapi_compute,metadata

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

   * In the ``[DEFAULT]`` section, configure the ``my_ip`` option:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        my_ip = MANAGEMENT_INTERFACE_IP_ADDRESS

     Replace ``MANAGEMENT_INTERFACE_IP_ADDRESS`` with the IP address of the
     management network interface on your compute node, typically 10.0.0.31 for
     the first node in the :ref:`example architecture
     <overview-example-architectures>`.

   * In the ``[DEFAULT]`` section, enable support for the Networking service:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [DEFAULT]
        # ...
        use_neutron = true
        firewall_driver = nova.virt.firewall.NoopFirewallDriver

     .. note::

        By default, Compute uses an internal firewall service. Since Networking
        includes a firewall service, you must disable the Compute firewall
        service by using the ``nova.virt.firewall.NoopFirewallDriver`` firewall
        driver.

   * Configure the ``[neutron]`` section of **/etc/nova/nova.conf**. Refer to
     the :neutron-doc:`Networking service install guide
     <install/compute-install-rdo.html#configure-the-compute-service-to-use-the-networking-service>`
     for more details.

   * In the ``[vnc]`` section, enable and configure remote console access:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [vnc]
        # ...
        enabled = true
        server_listen = 0.0.0.0
        server_proxyclient_address = $my_ip
        novncproxy_base_url = http://controller:6080/vnc_auto.html

     The server component listens on all IP addresses and the proxy component
     only listens on the management interface IP address of the compute node.
     The base URL indicates the location where you can use a web browser to
     access remote consoles of instances on this compute node.

     .. note::

        If the web browser to access remote consoles resides on a host that
        cannot resolve the ``controller`` hostname, you must replace
        ``controller`` with the management interface IP address of the
        controller node.

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

Finalize installation
---------------------

#. Determine whether your compute node supports hardware acceleration for
   virtual machines:

   .. code-block:: console

      $ egrep -c '(vmx|svm)' /proc/cpuinfo

   If this command returns a value of ``one or greater``, your compute node
   supports hardware acceleration which typically requires no additional
   configuration.

   If this command returns a value of ``zero``, your compute node does not
   support hardware acceleration and you must configure ``libvirt`` to use QEMU
   instead of KVM.

   * Edit the ``[libvirt]`` section in the ``/etc/nova/nova.conf`` file as
     follows:

     .. path /etc/nova/nova.conf
     .. code-block:: ini

        [libvirt]
        # ...
        virt_type = qemu

#. Start the Compute service including its dependencies and configure them to
   start automatically when the system boots:

   .. code-block:: console

      # systemctl enable libvirtd.service openstack-nova-compute.service
      # systemctl start libvirtd.service openstack-nova-compute.service

.. note::

   If the ``nova-compute`` service fails to start, check
   ``/var/log/nova/nova-compute.log``. The error message ``AMQP server on
   controller:5672 is unreachable`` likely indicates that the firewall on the
   controller node is preventing access to port 5672.  Configure the firewall
   to open port 5672 on the controller node and restart ``nova-compute``
   service on the compute node.

Add the compute node to the cell database
-----------------------------------------

.. important::

   Run the following commands on the **controller** node.

#. Source the admin credentials to enable admin-only CLI commands, then confirm
   there are compute hosts in the database:

   .. code-block:: console

      $ . admin-openrc

      $ openstack compute service list --service nova-compute
      +----+-------+--------------+------+-------+---------+----------------------------+
      | ID | Host  | Binary       | Zone | State | Status  | Updated At                 |
      +----+-------+--------------+------+-------+---------+----------------------------+
      | 1  | node1 | nova-compute | nova | up    | enabled | 2017-04-14T15:30:44.000000 |
      +----+-------+--------------+------+-------+---------+----------------------------+

#. Discover compute hosts:

   .. code-block:: console

      # su -s /bin/sh -c "nova-manage cell_v2 discover_hosts --verbose" nova

      Found 2 cell mappings.
      Skipping cell0 since it does not contain hosts.
      Getting compute nodes from cell 'cell1': ad5a5985-a719-4567-98d8-8d148aaae4bc
      Found 1 computes in cell: ad5a5985-a719-4567-98d8-8d148aaae4bc
      Checking host mapping for compute host 'compute': fe58ddc1-1d65-4f87-9456-bc040dc106b3
      Creating host mapping for compute host 'compute': fe58ddc1-1d65-4f87-9456-bc040dc106b3

   .. note::

      When you add new compute nodes, you must run ``nova-manage cell_v2
      discover_hosts`` on the controller node to register those new compute
      nodes. Alternatively, you can set an appropriate interval in
      ``/etc/nova/nova.conf``:

      .. code-block:: ini

         [scheduler]
         discover_hosts_in_cells_interval = 300
