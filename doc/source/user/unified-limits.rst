=====================
Unified Limits Quotas
=====================

Since the Nova 28.0.0 (2023.2 Bobcat) release, it is recommended to use
`Keystone unified limits`_ for Nova quota limits.

For information about legacy quota limits, see the :doc:`legacy quota
documentation </user/quotas>`.

Nova uses a quota system for setting limits on resources such as number of
instances or amount of CPU that a specific project or user can use.

Quota limits are set by admin and retrieved for enforcement using the `Keystone
API`_.

.. _Keystone unified limits: https://docs.openstack.org/keystone/latest/admin/unified-limits.html
.. _Keystone API: https://docs.openstack.org/api-ref/identity/v3/index.html#unified-limits

Types of quota
--------------

Unified limit resource names for resources that are tracked as `resource
classes`_ in the placement service follow the naming pattern of the ``class:``
prefix followed by the name of the resource class. For example: class:VCPU,
class:PCPU, class:MEMORY_MB, class:DISK_GB, class:VGPU.

.. list-table::
   :header-rows: 1
   :widths: 10 40

   * - Quota name
     - Description
   * - class:VCPU
     - Number of shared CPU cores (VCPUs) allowed per project.
   * - class:PCPU
     - Number of dedicated CPU cores (PCPUs) allowed per project.
   * - servers
     - Number of instances allowed per project.
   * - server_key_pairs
     - Number of key pairs allowed per user.
   * - server_metadata_items
     - Number of metadata items allowed per instance.
   * - class:MEMORY_MB
     - Megabytes of instance ram allowed per project.
   * - server_groups
     - Number of server groups per project.
   * - server_group_members
     - Number of servers per server group.
   * - class:DISK_GB
     - Gigabytes of instance disk allowed per project.
   * - class:<any resource class in the placement service>
     - Any resource class in the placement service that is allocated by Nova
       can have a quota limit specified for it. Example: class:VGPU.

.. _resource classes: https://docs.openstack.org/os-resource-classes/latest

The following quotas were previously available but were removed in microversion
2.36 as they proxied information available from the networking service.

.. list-table::
   :header-rows: 1
   :widths: 10 40

   * - Quota name
     - Description
   * - fixed_ips
     - Number of fixed IP addresses allowed per project. This number
       must be equal to or greater than the number of allowed
       instances.
   * - floating_ips
     - Number of floating IP addresses allowed per project.
   * - networks
     - Number of networks allowed per project (no longer used).
   * - security_groups
     - Number of security groups per project.
   * - security_group_rules
     - Number of security group rules per project.

Similarly, the following quotas were previously available but were removed in
microversion 2.57 as the personality files feature was deprecated.

.. list-table::
   :header-rows: 1
   :widths: 10 40

   * - Quota name
     - Description
   * - injected_files
     - Number of injected files allowed per project.
   * - injected_file_content_bytes
     - Number of content bytes allowed per injected file.
   * - injected_file_path_bytes
     - Length of injected file path.


Usage
-----

Project quotas
~~~~~~~~~~~~~~

To list all default quotas for projects, run:

.. code-block:: console

   $ openstack registered limit list

.. note::

   This lists default quotas for all services and not just nova.

For example:

.. code-block:: console

   $ openstack registered limit list
   +----------------------------------+----------------------------------+------------------------------------+---------------+-------------+-----------+
   | ID                               | Service ID                       | Resource Name                      | Default Limit | Description | Region ID |
   +----------------------------------+----------------------------------+------------------------------------+---------------+-------------+-----------+
   | eeee406035fc4a7892c6fc6fcc76e61a | b5d97619e6354c03be50c6b1589e6547 | image_size_total                   |          1000 | None        | RegionOne |
   | b99d35b1b7b74cd0a26a6311963328af | b5d97619e6354c03be50c6b1589e6547 | image_stage_total                  |          1000 | None        | RegionOne |
   | 70945789dad24082bc2a8cdbf53a5091 | b5d97619e6354c03be50c6b1589e6547 | image_count_total                  |           100 | None        | RegionOne |
   | 908d86c0ac3f46d0bb45ed9194710ea7 | b5d97619e6354c03be50c6b1589e6547 | image_count_uploading              |           100 | None        | RegionOne |
   | be6dfeebb7c340e8b93b602d41fbff9b | 8b22bf8a66fa4524a522b2a21865bbf2 | servers                            |            10 | None        | None      |
   | 8a658096236549788e61f4fcbd5a4a12 | 8b22bf8a66fa4524a522b2a21865bbf2 | class:VCPU                         |            20 | None        | None      |
   | 63890db7d6a14401ba55e7f7022b95d0 | 8b22bf8a66fa4524a522b2a21865bbf2 | class:MEMORY_MB                    |         51200 | None        | None      |
   | 221ba1c19d2c4272952663828d659013 | 8b22bf8a66fa4524a522b2a21865bbf2 | server_metadata_items              |           128 | None        | None      |
   | 8e61cabd2e854a11bdd2cf94efd702d1 | 8b22bf8a66fa4524a522b2a21865bbf2 | server_injected_files              |             5 | None        | None      |
   | 3d259390f70e4e9b88ecb2b0fa075f9b | 8b22bf8a66fa4524a522b2a21865bbf2 | server_injected_file_content_bytes |         10240 | None        | None      |
   | a12e10b991cc4bdd8e6ff30f6e6c15ac | 8b22bf8a66fa4524a522b2a21865bbf2 | server_injected_file_path_bytes    |           255 | None        | None      |
   | a32a9080be6b4a5481c16a91fe329e6f | 8b22bf8a66fa4524a522b2a21865bbf2 | server_key_pairs                   |           100 | None        | None      |
   | 86408bb7a0e542b18404ec7d348da820 | 8b22bf8a66fa4524a522b2a21865bbf2 | server_groups                      |            10 | None        | None      |
   | 17c4552c5aad4afca4813f37530fc897 | 8b22bf8a66fa4524a522b2a21865bbf2 | server_group_members               |            10 | None        | None      |
   +----------------------------------+----------------------------------+------------------------------------+---------------+-------------+-----------+

To show details about a default limit, run:

.. code-block:: console

   $ openstack registered limit show <registered-limit-id>

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

To list the currently set quota values for your project, run:

.. code-block:: console

   $ openstack limit list

For example:

.. code-block:: console

   $ openstack limit list
   +----------------------------------+----------------------------------+----------------------------------+---------------+----------------+-------------+-----------+
   | ID                               | Project ID                       | Service ID                       | Resource Name | Resource Limit | Description | Region ID |
   +----------------------------------+----------------------------------+----------------------------------+---------------+----------------+-------------+-----------+
   | 8b3364b2241e4090aaaa49355c7a5b56 | 5cd3281595a9497ba87209701cd9f3f2 | 8b22bf8a66fa4524a522b2a21865bbf2 | class:VCPU    |              5 | None        | None      |
   +----------------------------------+----------------------------------+----------------------------------+---------------+----------------+-------------+-----------+

To show details about a quota limimt, run:

.. code-block:: console

   $ openstack limit show <limit-id>

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
