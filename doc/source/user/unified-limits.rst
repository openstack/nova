=====================
Unified Limits Quotas
=====================

Since the **Nova 28.0.0 (2023.2 Bobcat)** release, it is recommended to use
`Keystone unified limits`_ for Nova quota limits.

For information about legacy quota limits, see the :doc:`legacy quota
documentation </user/quotas>`.

Nova uses a quota system for setting limits on resources such as number of
instances or amount of CPU that a specific project or user can use.

Quota limits are set by admin and retrieved for enforcement using the
`Keystone unified limits API`_.

.. _Keystone unified limits: https://docs.openstack.org/keystone/latest/admin/unified-limits.html
.. _Keystone unified limits API: https://docs.openstack.org/api-ref/identity/v3/index.html#unified-limits

Types of quota
--------------

Unified limit resource names for resources that are tracked as `resource
classes`_ in the Placement API service follow the naming pattern of the
``class:`` prefix followed by the name of the resource class. For example:
class:VCPU, class:PCPU, class:MEMORY_MB, class:DISK_GB, class:VGPU.

.. list-table::
   :header-rows: 1
   :widths: 10 40

   * - Quota name
     - Description
   * - class:VCPU
     - Number of shared CPU cores (VCPUs) allowed per project
   * - class:PCPU
     - Number of dedicated CPU cores (PCPUs) allowed per project
   * - servers
     - Number of instances allowed per project
   * - server_key_pairs
     - Number of key pairs allowed per user
   * - server_metadata_items
     - Number of metadata items allowed per instance
   * - class:MEMORY_MB
     - Megabytes of instance ram allowed per project
   * - server_groups
     - Number of server groups per project
   * - server_group_members
     - Number of servers per server group
   * - class:DISK_GB
     - Gigabytes of instance disk allowed per project
   * - class:$RESOURCE_CLASS
     - Any resource class in the Placement API service can have a quota limit
       specified for it (example: class:VGPU)

.. _resource classes: https://docs.openstack.org/os-resource-classes/latest


OpenStack CLI commands
----------------------

For full OpenStackClient documentation, see
https://docs.openstack.org/python-openstackclient/latest/index.html.

To list default limits for Nova:

.. code-block:: console

   openstack registered limit list --service nova

For example:

.. code-block:: console

   $ openstack registered limit list --service nova
   +----------------------------------+----------------------------------+------------------------------------+---------------+-------------+-----------+
   | ID                               | Service ID                       | Resource Name                      | Default Limit | Description | Region ID |
   +----------------------------------+----------------------------------+------------------------------------+---------------+-------------+-----------+
   | be6dfeebb7c340e8b93b602d41fbff9b | 8b22bf8a66fa4524a522b2a21865bbf2 | servers                            |            10 | None        | None      |
   | 8a658096236549788e61f4fcbd5a4a12 | 8b22bf8a66fa4524a522b2a21865bbf2 | class:VCPU                         |            20 | None        | None      |
   | 63890db7d6a14401ba55e7f7022b95d0 | 8b22bf8a66fa4524a522b2a21865bbf2 | class:MEMORY_MB                    |         51200 | None        | None      |
   | 221ba1c19d2c4272952663828d659013 | 8b22bf8a66fa4524a522b2a21865bbf2 | server_metadata_items              |           128 | None        | None      |
   | a32a9080be6b4a5481c16a91fe329e6f | 8b22bf8a66fa4524a522b2a21865bbf2 | server_key_pairs                   |           100 | None        | None      |
   | 86408bb7a0e542b18404ec7d348da820 | 8b22bf8a66fa4524a522b2a21865bbf2 | server_groups                      |            10 | None        | None      |
   | 17c4552c5aad4afca4813f37530fc897 | 8b22bf8a66fa4524a522b2a21865bbf2 | server_group_members               |            10 | None        | None      |
   +----------------------------------+----------------------------------+------------------------------------+---------------+-------------+-----------+

To show details about a default limit:

.. code-block:: console

   openstack registered limit show $REGISTERED_LIMIT_ID

For example:

.. code-block:: console

   $ openstack registered limit show 8a658096236549788e61f4fcbd5a4a12
   +---------------+----------------------------------+
   | Field         | Value                            |
   +---------------+----------------------------------+
   | default_limit | 20                               |
   | description   | None                             |
   | id            | 8a658096236549788e61f4fcbd5a4a12 |
   | region_id     | None                             |
   | resource_name | class:VCPU                       |
   | service_id    | 8b22bf8a66fa4524a522b2a21865bbf2 |
   +---------------+----------------------------------+

To list project limits for Nova:

.. code-block:: console

   openstack limit list --service nova

For example:

.. code-block:: console

   $ openstack limit list --service nova
   +----------------------------------+----------------------------------+----------------------------------+---------------+----------------+-------------+-----------+
   | ID                               | Project ID                       | Service ID                       | Resource Name | Resource Limit | Description | Region ID |
   +----------------------------------+----------------------------------+----------------------------------+---------------+----------------+-------------+-----------+
   | 8b3364b2241e4090aaaa49355c7a5b56 | 5cd3281595a9497ba87209701cd9f3f2 | 8b22bf8a66fa4524a522b2a21865bbf2 | class:VCPU    |              5 | None        | None      |
   +----------------------------------+----------------------------------+----------------------------------+---------------+----------------+-------------+-----------+

To list limits for a particular project:

.. code-block:: console

   openstack limit list --service nova --project $PROJECT_ID

To show details about a project limit:

.. code-block:: console

   openstack limit show $LIMIT_ID

For example:

.. code-block:: console

   $ openstack limit show 8b3364b2241e4090aaaa49355c7a5b56
   +----------------+----------------------------------+
   | Field          | Value                            |
   +----------------+----------------------------------+
   | description    | None                             |
   | domain_id      | None                             |
   | id             | 8b3364b2241e4090aaaa49355c7a5b56 |
   | project_id     | 5cd3281595a9497ba87209701cd9f3f2 |
   | region_id      | None                             |
   | resource_limit | 5                                |
   | resource_name  | class:VCPU                       |
   | service_id     | 8b22bf8a66fa4524a522b2a21865bbf2 |
   +----------------+----------------------------------+
