=============================
Manage Compute service quotas
=============================

As an administrative user, you can use the :command:`nova quota-*` commands,
which are provided by the ``python-novaclient`` package, to update the Compute
service quotas for a specific project or project user, as well as update the
quota defaults for a new project.

.. rubric:: Compute quota descriptions

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
     - Number of networks allowed per project (nova-network only).
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

View and update Compute quotas for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To view and update default quota values
---------------------------------------

#. List all default quotas for all projects:

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

   .. note::

      This lists default quotas for all services and not just nova.

#. Update a default value for a new project, for example:

   .. code-block:: console

      $ openstack quota set --instances 15 --class default

To view quota values for an existing project
--------------------------------------------

#. List the currently set quota values for a project:

   .. code-block:: console

      $ openstack quota show PROJECT_NAME
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

   .. note::

      This lists quotas for all services and not just nova.


To update quota values for an existing project
----------------------------------------------

#. Obtain the project ID.

   .. code-block:: console

      $ project=$(openstack project show -f value -c id PROJECT_NAME)

#. Update a particular quota value.

   To update quotas for a project:

   .. code-block:: console

      $ openstack quota set --QUOTA_NAME QUOTA_VALUE PROJECT_NAME

   To update quotas for a class:

   .. code-block:: console

      $ openstack quota set --class --QUOTA_NAME QUOTA_VALUE CLASS_NAME

   .. note::

      Only the ``default`` class is supported by nova.

   For example:

   .. code-block:: console

      $ openstack quota set --instances 50 PROJECT_NAME
      $ openstack quota show PROJECT_NAME
      +----------------------+----------------------------------+
      | Field                | Value                            |
      +----------------------+----------------------------------+
      | ...                  | ...                              |
      | instances            | 50                               |
      | ...                  | ...                              |
      +----------------------+----------------------------------+

   .. note::

      To view a list of options for the :command:`openstack quota set` command,
      run:

      .. code-block:: console

         $ openstack help quota set

View and update Compute quotas for a project user
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To view quota values for a project user
---------------------------------------

#. Place the user ID in a usable variable.

   .. code-block:: console

      $ projectUser=$(openstack user show -f value -c id USER_NAME)

#. Place the user's project ID in a usable variable, as follows:

   .. code-block:: console

      $ project=$(openstack project show -f value -c id PROJECT_NAME)

#. List the currently set quota values for a project user.

   .. code-block:: console

      $ nova quota-show --user $projectUser --tenant $project

   For example:

   .. code-block:: console

      $ nova quota-show --user $projectUser --tenant $project
      +-----------------------------+-------+
      | Quota                       | Limit |
      +-----------------------------+-------+
      | instances                   | 10    |
      | cores                       | 20    |
      | ram                         | 51200 |
      | floating_ips                | 20    |
      | fixed_ips                   | -1    |
      | metadata_items              | 128   |
      | injected_files              | 5     |
      | injected_file_content_bytes | 10240 |
      | injected_file_path_bytes    | 255   |
      | key_pairs                   | 100   |
      | security_groups             | 10    |
      | security_group_rules        | 20    |
      | server_groups               | 10    |
      | server_group_members        | 10    |
      +-----------------------------+-------+

To update quota values for a project user
-----------------------------------------

#. Place the user ID in a usable variable.

   .. code-block:: console

      $ projectUser=$(openstack user show -f value -c id USER_NAME)

#. Place the user's project ID in a usable variable, as follows:

   .. code-block:: console

      $ project=$(openstack project show -f value -c id PROJECT_NAME)

#. Update a particular quota value, as follows:

   .. code-block:: console

      $ nova quota-update  --user $projectUser --QUOTA_NAME QUOTA_VALUE $project

   For example:

   .. code-block:: console

      $ nova quota-update --user $projectUser --floating-ips 12 $project
      $ nova quota-show --user $projectUser --tenant $project
      +-----------------------------+-------+
      | Quota                       | Limit |
      +-----------------------------+-------+
      | instances                   | 10    |
      | cores                       | 20    |
      | ram                         | 51200 |
      | floating_ips                | 12    |
      | fixed_ips                   | -1    |
      | metadata_items              | 128   |
      | injected_files              | 5     |
      | injected_file_content_bytes | 10240 |
      | injected_file_path_bytes    | 255   |
      | key_pairs                   | 100   |
      | security_groups             | 10    |
      | security_group_rules        | 20    |
      | server_groups               | 10    |
      | server_group_members        | 10    |
      +-----------------------------+-------+

   .. note::

      To view a list of options for the :command:`nova quota-update` command,
      run:

      .. code-block:: console

         $ nova help quota-update

To display the current quota usage for a project user
-----------------------------------------------------

Use :command:`nova limits` to get a list of the
current quota values and the current quota usage:

.. code-block:: console

   $ nova limits --tenant PROJECT_NAME

   +------+-----+-------+--------+------+----------------+
   | Verb | URI | Value | Remain | Unit | Next_Available |
   +------+-----+-------+--------+------+----------------+
   +------+-----+-------+--------+------+----------------+

   +--------------------+------+-------+
   | Name               | Used | Max   |
   +--------------------+------+-------+
   | Cores              | 0    | 20    |
   | Instances          | 0    | 10    |
   | Keypairs           | -    | 100   |
   | Personality        | -    | 5     |
   | Personality Size   | -    | 10240 |
   | RAM                | 0    | 51200 |
   | Server Meta        | -    | 128   |
   | ServerGroupMembers | -    | 10    |
   | ServerGroups       | 0    | 10    |
   +--------------------+------+-------+

.. note::

   The :command:`nova limits` command generates an empty
   table as a result of the Compute API, which prints an
   empty list for backward compatibility purposes.
