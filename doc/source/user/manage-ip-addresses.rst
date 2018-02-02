===================
Manage IP addresses
===================

Each instance has a private, fixed IP address and can also have a
public, or floating IP address. Private IP addresses are used for
communication between instances, and public addresses are used for
communication with networks outside the cloud, including the Internet.

When you launch an instance, it is automatically assigned a private IP
address that stays the same until you explicitly terminate the instance.
Rebooting an instance has no effect on the private IP address.

A pool of floating IP addresses, configured by the cloud administrator,
is available in OpenStack Compute. The project quota defines the maximum
number of floating IP addresses that you can allocate to the project.
After you allocate a floating IP address to a project, you can:

- Associate the floating IP address with an instance of the project.

- Disassociate a floating IP address from an instance in the project.

- Delete a floating IP from the project which automatically deletes that IP's
  associations.

Use the :command:`openstack` commands to manage floating IP addresses.

List floating IP address information
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To list all pools that provide floating IP addresses, run:

.. code-block:: console

   $ openstack floating ip pool list
   +--------+
   | name   |
   +--------+
   | public |
   | test   |
   +--------+

.. note::

   If this list is empty, the cloud administrator must configure a pool
   of floating IP addresses.

To list all floating IP addresses that are allocated to the current project,
run:

.. code-block:: console

   $ openstack floating ip list
   +--------------------------------------+---------------------+------------------+------+
   | ID                                   | Floating IP Address | Fixed IP Address | Port |
   +--------------------------------------+---------------------+------------------+------+
   | 760963b2-779c-4a49-a50d-f073c1ca5b9e | 172.24.4.228        | None             | None |
   | 89532684-13e1-4af3-bd79-f434c9920cc3 | 172.24.4.235        | None             | None |
   | ea3ebc6d-a146-47cd-aaa8-35f06e1e8c3d | 172.24.4.229        | None             | None |
   +--------------------------------------+---------------------+------------------+------+

For each floating IP address that is allocated to the current project,
the command outputs the floating IP address, the ID for the instance
to which the floating IP address is assigned, the associated fixed IP
address, and the pool from which the floating IP address was
allocated.

Associate floating IP addresses
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can assign a floating IP address to a project and to an instance.

#. Run the following command to allocate a floating IP address to the
   current project. By default, the floating IP address is allocated from
   the public pool. The command outputs the allocated IP address:

   .. code-block:: console

      $ openstack floating ip create public
      +---------------------+--------------------------------------+
      | Field               | Value                                |
      +---------------------+--------------------------------------+
      | created_at          | 2016-11-30T15:02:05Z                 |
      | description         |                                      |
      | fixed_ip_address    | None                                 |
      | floating_ip_address | 172.24.4.236                         |
      | floating_network_id | 0bf90de6-fc0f-4dba-b80d-96670dfb331a |
      | headers             |                                      |
      | id                  | c70ad74b-2f64-4e60-965e-f24fc12b3194 |
      | port_id             | None                                 |
      | project_id          | 5669caad86a04256994cdf755df4d3c1     |
      | project_id          | 5669caad86a04256994cdf755df4d3c1     |
      | revision_number     | 1                                    |
      | router_id           | None                                 |
      | status              | DOWN                                 |
      | updated_at          | 2016-11-30T15:02:05Z                 |
      +---------------------+--------------------------------------+

#. List all project instances with which a floating IP address could be
   associated.

   .. code-block:: console

      $ openstack server list
      +---------------------+------+---------+------------+-------------+------------------+------------+
      | ID                  | Name | Status  | Task State | Power State | Networks         | Image Name |
      +---------------------+------+---------+------------+-------------+------------------+------------+
      | d5c854f9-d3e5-4f... | VM1  | ACTIVE  | -          | Running     | private=10.0.0.3 | cirros     |
      | 42290b01-0968-43... | VM2  | SHUTOFF | -          | Shutdown    | private=10.0.0.4 | centos     |
      +---------------------+------+---------+------------+-------------+------------------+------------+

   Note the server ID to use.

#. List ports associated with the selected server.

   .. code-block:: console

      $ openstack port list --device-id SERVER_ID
      +--------------------------------------+------+-------------------+--------------------------------------------------------------+--------+
      | ID                                   | Name | MAC Address       | Fixed IP Addresses                                           | Status |
      +--------------------------------------+------+-------------------+--------------------------------------------------------------+--------+
      | 40e9dea9-f457-458f-bc46-6f4ebea3c268 |      | fa:16:3e:00:57:3e | ip_address='10.0.0.4', subnet_id='23ee9de7-362e-             | ACTIVE |
      |                                      |      |                   | 49e2-a3b0-0de1c14930cb'                                      |        |
      |                                      |      |                   | ip_address='fd22:4c4c:81c2:0:f816:3eff:fe00:573e', subnet_id |        |
      |                                      |      |                   | ='a2b3acbe-fbeb-40d3-b21f-121268c21b55'                      |        |
      +--------------------------------------+------+-------------------+--------------------------------------------------------------+--------+

   Note the port ID to use.

#. Associate an IP address with an instance in the project, as follows:

   .. code-block:: console

      $ openstack floating ip set --port PORT_ID FLOATING_IP_ADDRESS

   For example:

   .. code-block:: console

      $ openstack floating ip set --port 40e9dea9-f457-458f-bc46-6f4ebea3c268 172.24.4.225

   The instance is now associated with two IP addresses:

   .. code-block:: console

      $ openstack server list
      +------------------+------+--------+------------+-------------+-------------------------------+------------+
      | ID               | Name | Status | Task State | Power State | Networks                      | Image Name |
      +------------------+------+--------+------------+-------------+-------------------------------+------------+
      | d5c854f9-d3e5... | VM1  | ACTIVE | -          | Running     | private=10.0.0.3, 172.24.4.225| cirros     |
      | 42290b01-0968... | VM2  | SHUTOFF| -          | Shutdown    | private=10.0.0.4              | centos     |
      +------------------+------+--------+------------+-------------+-------------------------------+------------+

   After you associate the IP address and configure security group rules
   for the instance, the instance is publicly available at the floating IP
   address.

Disassociate floating IP addresses
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To disassociate a floating IP address from an instance:

.. code-block:: console

   $ openstack floating ip unset --port FLOATING_IP_ADDRESS

To remove the floating IP address from a project:

.. code-block:: console

   $ openstack floating ip delete FLOATING_IP_ADDRESS

The IP address is returned to the pool of IP addresses that is available
for all projects. If the IP address is still associated with a running
instance, it is automatically disassociated from that instance.
