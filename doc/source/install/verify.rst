Verify operation
~~~~~~~~~~~~~~~~

Verify operation of the Compute service.

.. note::

   Perform these commands on the controller node.

#. Source the ``admin`` credentials to gain access to admin-only CLI commands:

   .. code-block:: console

      $ . admin-openrc

#. List service components to verify successful launch and registration of each
   process:

   .. code-block:: console

      $ openstack compute service list

      +----+--------------------+------------+----------+---------+-------+----------------------------+
      | Id | Binary             | Host       | Zone     | Status  | State | Updated At                 |
      +----+--------------------+------------+----------+---------+-------+----------------------------+
      |  1 | nova-scheduler     | controller | internal | enabled | up    | 2016-02-09T23:11:15.000000 |
      |  2 | nova-conductor     | controller | internal | enabled | up    | 2016-02-09T23:11:16.000000 |
      |  3 | nova-compute       | compute1   | nova     | enabled | up    | 2016-02-09T23:11:20.000000 |
      +----+--------------------+------------+----------+---------+-------+----------------------------+

   .. note::

      This output should indicate two service components enabled on the
      controller node and one service component enabled on the compute node.

#. List API endpoints in the Identity service to verify connectivity with the
   Identity service:

   .. note::

      Below endpoints list may differ depending on the installation of
      OpenStack components.

   .. code-block:: console

      $ openstack catalog list

      +-----------+-----------+-----------------------------------------+
      | Name      | Type      | Endpoints                               |
      +-----------+-----------+-----------------------------------------+
      | keystone  | identity  | RegionOne                               |
      |           |           |   public: http://controller:5000/v3/    |
      |           |           | RegionOne                               |
      |           |           |   internal: http://controller:5000/v3/  |
      |           |           | RegionOne                               |
      |           |           |   admin: http://controller:5000/v3/     |
      |           |           |                                         |
      | glance    | image     | RegionOne                               |
      |           |           |   admin: http://controller:9292         |
      |           |           | RegionOne                               |
      |           |           |   public: http://controller:9292        |
      |           |           | RegionOne                               |
      |           |           |   internal: http://controller:9292      |
      |           |           |                                         |
      | nova      | compute   | RegionOne                               |
      |           |           |   admin: http://controller:8774/v2.1    |
      |           |           | RegionOne                               |
      |           |           |   internal: http://controller:8774/v2.1 |
      |           |           | RegionOne                               |
      |           |           |   public: http://controller:8774/v2.1   |
      |           |           |                                         |
      | placement | placement | RegionOne                               |
      |           |           |   public: http://controller:8778        |
      |           |           | RegionOne                               |
      |           |           |   admin: http://controller:8778         |
      |           |           | RegionOne                               |
      |           |           |   internal: http://controller:8778      |
      |           |           |                                         |
      +-----------+-----------+-----------------------------------------+

   .. note::

      Ignore any warnings in this output.

#. List images in the Image service to verify connectivity with the Image
   service:

   .. code-block:: console

      $ openstack image list

      +--------------------------------------+-------------+-------------+
      | ID                                   | Name        | Status      |
      +--------------------------------------+-------------+-------------+
      | 9a76d9f9-9620-4f2e-8c69-6c5691fae163 | cirros      | active      |
      +--------------------------------------+-------------+-------------+

#. Check the cells and placement API are working successfully and that other
   necessary prerequisites are in place:

   .. _verify-install-nova-status:

   .. code-block:: console

      # nova-status upgrade check

      +--------------------------------------------------------------------+
      | Upgrade Check Results                                              |
      +--------------------------------------------------------------------+
      | Check: Cells v2                                                    |
      | Result: Success                                                    |
      | Details: None                                                      |
      +--------------------------------------------------------------------+
      | Check: Placement API                                               |
      | Result: Success                                                    |
      | Details: None                                                      |
      +--------------------------------------------------------------------+
      | Check: Ironic Flavor Migration                                     |
      | Result: Success                                                    |
      | Details: None                                                      |
      +--------------------------------------------------------------------+
      | Check: Cinder API                                                  |
      | Result: Success                                                    |
      | Details: None                                                      |
      +--------------------------------------------------------------------+
      | Check: Policy Scope-based Defaults                                 |
      | Result: Success                                                    |
      | Details: None                                                      |
      +--------------------------------------------------------------------+
      | Check: Policy File JSON to YAML Migration                          |
      | Result: Success                                                    |
      | Details: None                                                      |
      +--------------------------------------------------------------------+
      | Check: Older than N-1 computes                                     |
      | Result: Success                                                    |
      | Details: None                                                      |
      +--------------------------------------------------------------------+
