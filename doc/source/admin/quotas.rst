=============
Manage quotas
=============

.. note::

    This section provides deployment information about the quota feature. For
    end-user information about quotas, including information about the type of
    quotas available, refer to the :doc:`user guide </user/quotas>`.

To prevent system capacities from being exhausted without notification, you can
set up quotas. Quotas are operational limits. For example, the number of
gigabytes allowed for each project can be controlled so that cloud resources
are optimized. Quotas can be enforced at both the project and the project-user
level.

Starting in the 16.0.0 Pike release, the quota calculation system in nova was
overhauled and the old reserve/commit/rollback flow was changed to `count
resource usage`__ at the point of whatever operation is being performed, such
as creating or resizing a server. A check will be performed by counting current
usage for the relevant resource and then, if
:oslo.config:option:`quota.recheck_quota` is True, another check will be
performed to ensure the initial check is still valid.

By default resource usage is counted using the API and cell databases but nova
can be configured to count some resource usage without using the cell
databases. See `Quota usage from placement`_ for details.

Using the command-line interface, you can manage quotas for nova, along with
:cinder-doc:`cinder <cli/cli-cinder-quotas.html>` and :neutron-doc:`neutron
<contributor/internals/quota.html>`. You would typically change default values
because, for example, a project requires more than ten volumes or 1 TB on a
compute node.

__ https://specs.openstack.org/openstack/nova-specs/specs/pike/implemented/cells-count-resources-to-check-quota-in-api.html


Checking quota
--------------

When calculating limits for a given resource and project, the following checks
are made in order:

#. Project-specific limits

   Depending on the resource, is there a project-specific limit on the
   resource in either the ``quotas`` or ``project_user_quotas`` tables in the
   database?  If so, use that as the limit. You can create these resources
   using:

   .. code-block:: console

       $ openstack quota set --instances 5 <project>

#. Default limits

   Check to see if there is a hard limit for the given resource in the
   ``quota_classes`` table in the database for the ``default`` quota class. If
   so, use that as the limit. You can modify the default quota limit for a
   resource using:

   .. code-block:: console

       $ openstack quota set --instances 5 --class default

   .. note::

       Only the ``default`` class is supported by nova.

#. Config-driven limits

   If the above does not provide a resource limit, then rely on the
   configuration options in the :oslo.config:group:`quota` config group for
   the default limits.

.. note::

    The API sets the limit in the ``quota_classes`` table. Once a default limit
    is set via the `default` quota class, that takes precedence over any
    changes to that resource limit in the configuration options. In other
    words, once you've changed things via the API, you either have to keep
    those synchronized with the configuration values or remove the default
    limit from the database manually as there is no REST API for removing quota
    class values from the database.


.. _quota-usage-from-placement:

Quota usage from placement
--------------------------

Starting in the Train (20.0.0) release, it is possible to configure quota usage
counting of cores and RAM from the placement service and instances from
instance mappings in the API database instead of counting resources from cell
databases. This makes quota usage counting resilient in the presence of `down
or poor-performing cells`__.

Quota usage counting from placement is opt-in via the
::oslo.config:option:`quota.count_usage_from_placement` config option:

.. code-block:: ini

    [quota]
    count_usage_from_placement = True

There are some things to note when opting in to counting quota usage from
placement:

* Counted usage will not be accurate in an environment where multiple Nova
  deployments are sharing a placement deployment because currently placement
  has no way of partitioning resource providers between different Nova
  deployments. Operators who are running multiple Nova deployments that share a
  placement deployment should not set the
  :oslo.config:option:`quota.count_usage_from_placement` configuration option
  to ``True``.

* Behavior will be different for resizes. During a resize, resource allocations
  are held on both the source and destination (even on the same host, see
  https://bugs.launchpad.net/nova/+bug/1790204) until the resize is confirmed
  or reverted. Quota usage will be inflated for servers in this state and
  operators should weigh the advantages and disadvantages before enabling
  :oslo.config:option:`quota.count_usage_from_placement`.

* The ``populate_queued_for_delete`` and ``populate_user_id`` online data
  migrations must be completed before usage can be counted from placement.
  Until the data migration is complete, the system will fall back to legacy
  quota usage counting from cell databases depending on the result of an EXISTS
  database query during each quota check, if
  :oslo.config:option:`quota.count_usage_from_placement` is set to ``True``.
  Operators who want to avoid the performance hit from the EXISTS queries
  should wait to set the :oslo.config:option:`quota.count_usage_from_placement`
  configuration option to ``True`` until after they have completed their online
  data migrations via ``nova-manage db online_data_migrations``.

* Behavior will be different for unscheduled servers in ``ERROR`` state. A
  server in ``ERROR`` state that has never been scheduled to a compute host
  will not have placement allocations, so it will not consume quota usage for
  cores and ram.

* Behavior will be different for servers in ``SHELVED_OFFLOADED`` state. A
  server in ``SHELVED_OFFLOADED`` state will not have placement allocations, so
  it will not consume quota usage for cores and ram. Note that because of this,
  it will be possible for a request to unshelve a server to be rejected if the
  user does not have enough quota available to support the cores and ram needed
  by the server to be unshelved.

__ https://docs.openstack.org/api-guide/compute/down_cells.html


Known issues
------------

If not :ref:`counting quota usage from placement <quota-usage-from-placement>`
it is possible for down or poor-performing cells to impact quota calculations.
See the :ref:`cells documentation <cells-counting-quotas>` for details.


Future plans
------------

Hierarchical quotas
~~~~~~~~~~~~~~~~~~~

There has long been a desire to support hierarchical or nested quotas
leveraging support in the identity service for hierarchical projects.
See the `unified limits`__ spec for details.

__ https://review.opendev.org/#/c/602201/


Configuration
-------------

View and update default quota values
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To list all default quotas for a project, run:

.. code-block:: console

    $ openstack quota show --default

.. note::

    This lists default quotas for all services and not just nova.

To update a default value for a new project, run:

.. code-block:: console

    $ openstack quota set --class --instances 15 default

View and update quota values for a project or class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To list quotas for a project, run:

.. code-block:: console

    $ openstack quota show PROJECT

.. note::

    This lists project quotas for all services and not just nova.

To update quotas for a project, run:

.. code-block:: console

    $ openstack quota set --QUOTA QUOTA_VALUE PROJECT

To update quotas for a class, run:

.. code-block:: console

    $ openstack quota set --class --QUOTA QUOTA_VALUE CLASS

.. note::

    Only the ``default`` class is supported by nova.

For example:

.. code-block:: console

    $ openstack quota set --instances 12 my-project
    $ openstack quota show my-project
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
    | instances            | 12                               |
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

To view a list of options for the :command:`openstack quota show` and
:command:`openstack quota set` commands, run:

.. code-block:: console

    $ openstack quota show --help
    $ openstack quota set --help

View and update quota values for a project user
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::

    User-specific quotas are legacy and will be removed when migration to
    :keystone-doc:`unified limits </admin/unified-limits.html>` is complete.
    User-specific quotas were added as a way to provide two-level hierarchical
    quotas and this feature is already being offered in unified limits. For
    this reason, the below commands have not and will not be ported to
    openstackclient.

To show quotas for a specific project user, run:

.. code-block:: console

    $ nova quota-show --user USER PROJECT

To update quotas for a specific project user, run:

.. code-block:: console

    $ nova quota-update --user USER --QUOTA QUOTA_VALUE PROJECT

For example:

.. code-block:: console

    $ projectUser=$(openstack user show -f value -c id USER)
    $ project=$(openstack project show -f value -c id PROJECT)

    $ nova quota-update --user $projectUser --instance 12 $project
    $ nova quota-show --user $projectUser --tenant $project
    +-----------------------------+-------+
    | Quota                       | Limit |
    +-----------------------------+-------+
    | instances                   | 12    |
    | cores                       | 20    |
    | ram                         | 51200 |
    | floating_ips                | 10    |
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

To view the quota usage for the current user, run:

.. code-block:: console

    $ nova limits --tenant PROJECT

For example:

.. code-block:: console

    $ nova limits --tenant my-project
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

   The :command:`nova limits` command generates an empty table as a result of
   the Compute API, which prints an empty list for backward compatibility
   purposes.

To view a list of options for the :command:`nova quota-show` and
:command:`nova quota-update` commands, run:

.. code-block:: console

    $ nova help quota-show
    $ nova help quota-update
