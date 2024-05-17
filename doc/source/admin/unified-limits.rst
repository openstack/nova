============================
Manage Unified Limits Quotas
============================

.. note::

    This section provides deployment information about the quota feature. For
    end-user information about quotas, including information about the type
    of quotas available, refer to the :doc:`user guide
    </user/unified-limits>`.

Since the **Nova 28.0.0 (2023.2 Bobcat)** release, it is recommended to use
`Keystone unified limits`_ for Nova quota limits.

For information about legacy quota limits, see the :doc:`legacy quota
documentation </admin/quotas>`.


Quotas
------

To prevent system capacities from being exhausted without notification, you
can set up quotas. Quotas are operational limits. The number of servers
allowed for each project can be controlled so that cloud resources are
optimized, for example. Quotas can be enforced at both the global
(default) level and at the project level.


Unified limits
--------------

Unified limits is a modern quota system in which quota limits are centralized
in the Keystone identity service. There are three steps for quota enforcement
in this model:

#. Quota limits are retrieved by calling the `Keystone unified limits API`_

#. Quota usage is counted from the `Placement API service`_

#. Quota is enforced locally using the `oslo.limit`_ limit enforcement
   library

In unified limits, the terminology is a bit different from legacy quotas:

* A **registered limit** is a global or default limit that applies to all
  projects

* A **limit** is a project-scoped limit that applies to a particular project

Cloud operators will need to manage their quota limits in the Keystone service
by calling the API directly or by using the OpenStackClient (OSC) `registered
limit`_ and `limit`_ commands.

.. _Keystone unified limits:
    https://docs.openstack.org/keystone/latest/admin/unified-limits.html
.. _Keystone unified limits API:
    https://docs.openstack.org/api-ref/identity/v3/index.html#unified-limits
.. _Placement API service: https://docs.openstack.org/placement
.. _oslo.limit: https://docs.openstack.org/oslo.limit
.. _registered limit:
    https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/registered-limit.html
.. _limit:
    https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/limit.html


Roles
~~~~~

By default Keystone API policy, a user must have the following roles and
scopes in order to perform actions with unified limits.

.. list-table::
   :header-rows: 1
   :widths: 10 20 20

   * - Action
     - Role
     - Scope
   * - List registered limits
     - ``*``
     - ``*``
   * - Get registered limit
     - ``*``
     - ``*``
   * - Create registered limit
     - ``admin``
     - ``system=all``
   * - Update registered limit
     - ``admin``
     - ``system=all``
   * - Delete registered limit
     - ``admin``
     - ``system=all``
   * - List limits
     - ``*``
     - ``*``
   * - Get limit
     - ``*``
     - ``*``
   * - Create limit
     - ``admin``
     - ``system=all``
   * - Update limit
     - ``admin``
     - ``system=all``
   * - Delete limit
     - ``admin``
     - ``system=all``


Configuration
-------------

To enable unified limits quotas, some Nova configuration of
the :program:`nova-api` and :program:`nova-conductor` services is necessary.

Set the quota driver to the ``nova.quota.UnifiedLimitsDriver``:

.. code-block:: ini

   [quota]
   driver = nova.quota.UnifiedLimitsDriver

Add a configuration section for oslo.limit:

.. code-block:: ini

   [oslo_limit]
   username = nova
   user_domain_name = $SERVICE_DOMAIN_NAME
   auth_url = $KEYSTONE_SERVICE_URI
   auth_type = password
   password = $SERVICE_PASSWORD
   system_scope = all
   endpoint_id = $SERVICE_ENDPOINT_ID

.. note::

   The Nova service endpoint ID can be obtained by ``openstack endpoint
   list --service nova -f value -c ID``

Ensure that the ``nova`` service user has the ``reader`` role with ``system``
scope:

.. code-block:: console

   openstack role add --user nova --user-domain $SERVICE_DOMAIN_NAME \
      --system all reader


Setting quota limits on resources
---------------------------------

Any resource that can be requested in the cloud must have a registered limit
set. Quota checks on cloud resources that do not have registered limits will
continue to fail until registered limits are set because oslo.limit considers
an unregistered resource to have a limit of 0.

Types of quota
~~~~~~~~~~~~~~

Unified limit resource names for resources that are tracked as `resource
classes`_ in the Placement API service follow the naming pattern of the
``class:`` prefix followed by the name of the resource class. For example:
class:VCPU, class:PCPU, class:MEMORY_MB, class:DISK_GB, class:VGPU.

.. list-table::
   :header-rows: 1
   :widths: 10 40

   * - Quota Name
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
~~~~~~~~~~~~~~~~~~~~~~

For full OpenStackClient documentation, see
https://docs.openstack.org/python-openstackclient/latest/index.html.

Registered Limits
^^^^^^^^^^^^^^^^^

To list default limits for Nova:

.. code-block:: console

   openstack registered limit list --service nova

To show details about a default limit:

.. code-block:: console

   openstack registered limit show $REGISTERED_LIMIT_ID

To create a default limit:

.. code-block:: console

   openstack registered limit create --service nova --default-limit $LIMIT \
      $RESOURCE

To update a default limit:

.. code-block:: console

   openstack registered limit set --resource-name $RESOURCE \
      --default-limit $LIMIT $REGISTERED_LIMIT_ID

To delete a default limit:

.. code-block:: console

   openstack registered limit delete $REGISTERED_LIMIT_ID

Limits
^^^^^^

To list project limits for Nova:

.. code-block:: console

   openstack limit list --service nova

To list limits for a particular project:

.. code-block:: console

   openstack limit list --service nova --project $PROJECT_ID

To show details about a project limit:

.. code-block:: console

   openstack limit show $LIMIT_ID

To create a project limit:

.. code-block:: console

   openstack limit create --service nova --project $PROJECT_ID \
      --resource-limit $LIMIT $RESOURCE

To update a project limit:

.. code-block:: console

   openstack limit set --resource-name $RESOURCE --resource-limit $LIMIT \
      $LIMIT_ID

To delete a project limit:

.. code-block:: console

   openstack limit delete $LIMIT_ID


Quota enforcement
-----------------

When enforcing limits for a given resource and project, the following checks
are made in order:

#. Limits (project-specific)

   Depending on the resource, is there a project-specific limit on the
   resource in Keystone limits? If so, use that as the limit. If not, proceed
   to check the registered default limit.

#. Registered limits (default)

   Depending on the resource, is there a default limit on the resource in
   Keystone limits? If so, use that as the limit. If not, oslo.limit will
   consider the limit as 0, the quota check will fail, and a quota limit
   exceeded exception will be raised.

.. warning::

   Every resource that can be requested in the cloud **must** at a minimum
   have a registered limit set. Any resource that does **not** have a
   registered limit set will fail quota enforcement because oslo.limit
   considers an unregistered resource to have a limit of **0**.


Rechecking quota
~~~~~~~~~~~~~~~~

If :oslo.config:option:`quota.recheck_quota` = True (this is the default),
Nova will perform a second quota check after allocating resources. The first
quota check is performed before resources are allocated. Rechecking quota
ensures that quota limits are strictly enforced and prevents any possibility
of resource allocation going over the quota limit in the event of racing
parallel API requests.

It can be disabled by setting :oslo.config:option:`quota.recheck_quota` =
False if strict quota enforcement is not important to the operator.


Quota usage from Placement
--------------------------

With unified limits quotas, it is required that quota resource usage is
counted from the Placement API service. As such,
the :oslo.config:option:`quota.count_usage_from_placement` configuration
option is ignored when :oslo.config:option:`quota.driver` is set to
``nova.quota.UnifiedLimitsDriver``.

There are some things to note when quota resource usage is counted from the
Placement API service:

* Counted usage will not be accurate in an environment where multiple Nova
  deployments are sharing a Placement deployment because currently Placement
  has no way of partitioning resource providers between different Nova
  deployments. Operators who are running multiple Nova deployments that share
  a Placement deployment should not use the ``nova.quota.UnifiedLimitsDriver``.

* Behavior will be different for resizes. During a resize, resource
  allocations are held on both the source and destination (even on the same
  host, see https://bugs.launchpad.net/nova/+bug/1790204) until the resize is
  confirmed or reverted. Quota usage will be inflated for servers in this
  state.

* The ``populate_queued_for_delete`` and ``populate_user_id`` online data
  migrations must be completed before usage can be counted from Placement.
  Until the data migration is complete, the system will fall back to legacy
  quota usage counting from cell databases depending on the result of an
  EXISTS database query during each quota check. Use ``nova-manage db
  online_data_migrations`` to run online data migrations.

* Behavior will be different for unscheduled servers in ``ERROR`` state. A
  server in ``ERROR`` state that has never been scheduled to a compute host
  will not have Placement allocations, so it will not consume quota usage for
  cores and ram.

* Behavior will be different for servers in ``SHELVED_OFFLOADED`` state. A
  server in ``SHELVED_OFFLOADED`` state will not have Placement allocations,
  so it will not consume quota usage for cores and ram. Note that because of
  this, it will be possible for a request to unshelve a server to be rejected
  if the user does not have enough quota available to support the cores and
  ram needed by the server to be unshelved.


Migration to unified limits quotas
----------------------------------

There is a `nova-manage`_ command available to help with moving from legacy
Nova database quotas to Keystone unified limits quotas. The command will read
quota limits from the Nova database and call the Keystone API to create the
corresponding unified limits.

.. code-block:: console

   $ nova-manage limits migrate_to_unified_limits -h
   usage: nova-manage limits migrate_to_unified_limits
   [-h] [--project-id <project-id>] [--region-id <region-id>] [--verbose]
   [--dry-run]

   Copy quota limits from the Nova API database to Keystone.

   options:
     -h, --help            show this help message and exit
     --project-id <project-id>
                           Project ID for which to migrate quota limits
     --region-id <region-id>
                           Region ID for which to migrate quota limits
     --verbose             Provide verbose output during execution.
     --dry-run             Show what limits would be created without actually
                           creating them.

.. important::

   Per-user quota limits will **not** be copied into Keystone because per-user
   quotas are not supported in unified limits.

.. _nova-manage: https://docs.openstack.org/nova/latest/cli/nova-manage.html#limits-migrate-to-unified-limits
