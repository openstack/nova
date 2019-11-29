======
Quotas
======

Nova uses a quota system for setting limits on resources such as number of
instances or amount of CPU that a specific project or user can use.

Quota limits and usage can be retrieved using the command-line interface.


Types of quota
--------------

.. list-table::
   :header-rows: 1
   :widths: 10 40

   * - Quota name
     - Description
   * - cores
     - Number of instance cores (VCPUs) allowed per project.
   * - instances
     - Number of instances allowed per project.
   * - key_pairs
     - Number of key pairs allowed per user.
   * - metadata_items
     - Number of metadata items allowed per instance.
   * - ram
     - Megabytes of instance ram allowed per project.
   * - server_groups
     - Number of server groups per project.
   * - server_group_members
     - Number of servers per server group.

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

    $ openstack quota show --default

.. note::

    This lists default quotas for all services and not just nova.

For example:

.. code-block:: console

    $ openstack quota show --default
    +----------------------+----------+
    | Field                | Value    |
    +----------------------+----------+
    | backup-gigabytes     | 1000     |
    | backups              | 10       |
    | cores                | 20       |
    | fixed-ips            | -1       |
    | floating-ips         | 50       |
    | gigabytes            | 1000     |
    | health_monitors      | None     |
    | injected-file-size   | 10240    |
    | injected-files       | 5        |
    | injected-path-size   | 255      |
    | instances            | 10       |
    | key-pairs            | 100      |
    | l7_policies          | None     |
    | listeners            | None     |
    | load_balancers       | None     |
    | location             | None     |
    | name                 | None     |
    | networks             | 10       |
    | per-volume-gigabytes | -1       |
    | pools                | None     |
    | ports                | 50       |
    | project              | None     |
    | project_name         | project  |
    | properties           | 128      |
    | ram                  | 51200    |
    | rbac_policies        | 10       |
    | routers              | 10       |
    | secgroup-rules       | 100      |
    | secgroups            | 10       |
    | server-group-members | 10       |
    | server-groups        | 10       |
    | snapshots            | 10       |
    | subnet_pools         | -1       |
    | subnets              | 10       |
    | volumes              | 10       |
    +----------------------+----------+

To list the currently set quota values for your project, run:

.. code-block:: console

    $ openstack quota show PROJECT

where ``PROJECT`` is the ID or name of your project. For example:

.. code-block:: console

    $ openstack quota show $OS_PROJECT_ID
    +----------------------+----------------------------------+
    | Field                | Value                            |
    +----------------------+----------------------------------+
    | backup-gigabytes     | 1000                             |
    | backups              | 10                               |
    | cores                | 32                               |
    | fixed-ips            | -1                               |
    | floating-ips         | 10                               |
    | gigabytes            | 1000                             |
    | health_monitors      | None                             |
    | injected-file-size   | 10240                            |
    | injected-files       | 5                                |
    | injected-path-size   | 255                              |
    | instances            | 10                               |
    | key-pairs            | 100                              |
    | l7_policies          | None                             |
    | listeners            | None                             |
    | load_balancers       | None                             |
    | location             | None                             |
    | name                 | None                             |
    | networks             | 20                               |
    | per-volume-gigabytes | -1                               |
    | pools                | None                             |
    | ports                | 60                               |
    | project              | c8156b55ec3b486193e73d2974196993 |
    | project_name         | project                          |
    | properties           | 128                              |
    | ram                  | 65536                            |
    | rbac_policies        | 10                               |
    | routers              | 10                               |
    | secgroup-rules       | 50                               |
    | secgroups            | 50                               |
    | server-group-members | 10                               |
    | server-groups        | 10                               |
    | snapshots            | 10                               |
    | subnet_pools         | -1                               |
    | subnets              | 20                               |
    | volumes              | 10                               |
    +----------------------+----------------------------------+

To view a list of options for the :command:`openstack quota show` command, run:

.. code-block:: console

    $ openstack quota show --help

User quotas
~~~~~~~~~~~

.. note::

    User-specific quotas are legacy and will be removed when migration to
    :keystone-doc:`unified limits </admin/unified-limits.html>` is complete.
    User-specific quotas were added as a way to provide two-level hierarchical
    quotas and this feature is already being offered in unified limits. For
    this reason, the below commands have not and will not be ported to
    openstackclient.

To list the quotas for your user, run:

.. code-block:: console

    $ nova quota-show --user USER --tenant PROJECT

where ``USER`` is the ID or name of your user and ``PROJECT`` is the ID or name
of your project. For example:

.. code-block:: console

    $ nova quota-show --user $OS_USERNAME --tenant $OS_PROJECT_ID
    +-----------------------------+-------+
    | Quota                       | Limit |
    +-----------------------------+-------+
    | instances                   | 10    |
    | cores                       | 32    |
    | ram                         | 65536 |
    | metadata_items              | 128   |
    | injected_files              | 5     |
    | injected_file_content_bytes | 10240 |
    | injected_file_path_bytes    | 255   |
    | key_pairs                   | 100   |
    | server_groups               | 10    |
    | server_group_members        | 10    |
    +-----------------------------+-------+

To view a list of options for the :command:`nova quota-show` command, run:

.. code-block:: console

    $ nova help quota-show
