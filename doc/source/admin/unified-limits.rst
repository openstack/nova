============================
Manage Unified Limits Quotas
============================

.. note::

    This section provides deployment information about the quota feature. For
    end-user information about quotas, including information about the type of
    quotas available, refer to the :doc:`user guide </user/unified-limits>`.

Since the Nova 28.0.0 (2023.2 Bobcat) release, it is recommended to use
`Keystone unified limits`_ for Nova quota limits.

For information about legacy quota limits, see the :doc:`legacy quota
documentation </admin/quotas>`.

To enable unified limits quotas, set the quota driver in the Nova
configuration:

.. code-block:: ini

   [quota]
   driver = nova.quota.UnifiedLimitsDriver

Quota limits are set and retrieved for enforcement using the `Keystone API`_.

.. _Keystone unified limits: https://docs.openstack.org/keystone/latest/admin/unified-limits.html
.. _Keystone API: https://docs.openstack.org/api-ref/identity/v3/index.html#unified-limits

To prevent system capacities from being exhausted without notification, you can
set up quotas. Quotas are operational limits. For example, the number of
servers allowed for each project can be controlled so that cloud resources
are optimized. Quotas can be enforced at both the global (default) and the
project level.

Resource usage is counted from the placement service with unified limits.


Checking quota
--------------

When calculating limits for a given resource and project, the following checks
are made in order:

#. Project-specific limits

   Depending on the resource, is there a project-specific limit on the resource
   in Keystone limits? If so, use that as the limit. You can create these
   resource limits using:

   .. code-block:: console

      $ openstack limit create --service nova --project <project> --resource-limit 5 servers

#. Default limits

   Use the Keystone registered limit for the resource as the limit. You can
   create these default limits using:

   .. code-block:: console

      $ openstack registered limit create --service nova --default-limit 5 servers


Rechecking quota
~~~~~~~~~~~~~~~~

If :oslo.config:option:`quota.recheck_quota` is True (this is the default),
Nova will perform a second quota check after allocating resources. The first
quota check is performed before resources are allocated. Rechecking quota
ensures that quota limits are strictly enforced and prevents any possibility of
resource allocation going over the quota limit in the event of racing parallel
API requests.

It can be disabled by setting :oslo.config:option:`quota.recheck_quota` to
False if strict quota enforcement is not important to the operator.


Quota usage from placement
--------------------------

With unified limits quotas, it is required that quota resource usage is counted
from placement. As such, the
:oslo.config:option:`quota.count_usage_from_placement` configuration option is
ignored when :oslo.config:option:`quota.driver` is set to
``nova.quota.UnifiedLimitsDriver``.

There are some things to note when quota resource usage is counted from
placement:

* Counted usage will not be accurate in an environment where multiple Nova
  deployments are sharing a placement deployment because currently placement
  has no way of partitioning resource providers between different Nova
  deployments. Operators who are running multiple Nova deployments that share a
  placement deployment should not use the ``nova.quota.UnifiedLimitsDriver``.

* Behavior will be different for resizes. During a resize, resource allocations
  are held on both the source and destination (even on the same host, see
  https://bugs.launchpad.net/nova/+bug/1790204) until the resize is confirmed
  or reverted. Quota usage will be inflated for servers in this state.

* The ``populate_queued_for_delete`` and ``populate_user_id`` online data
  migrations must be completed before usage can be counted from placement.
  Until the data migration is complete, the system will fall back to legacy
  quota usage counting from cell databases depending on the result of an EXISTS
  database query during each quota check. Use
  ``nova-manage db online_data_migrations`` to run online data migrations.

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


Configuration
-------------

View and update default quota values
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To list all default quotas for a project, run:

.. code-block:: console

   $ openstack registered limit list

.. note::

   This lists default quotas for all services and not just nova.

To show details about a default limit, run:

.. code-block:: console

   $ openstack registered limit show <registered-limit-id>

To create a default quota limit, run:

.. code-block:: console

   $ openstack registered limit create --service nova --default-limit <value> <resource-name>

.. note::

   Creating or updating registered limits requires a system-scoped
   authorization token by default. See the `Keystone tokens documentation`_ for
   more information.

   .. _Keystone tokens documentation: https://docs.openstack.org/keystone/latest/admin/tokens-overview.html#operation_create_system_token

To update a default quota value, run:

.. code-block:: console

   $ openstack registered limit set --default-limit <value> <registered-limit-id>

To delete a default quota limit, run:

.. code-block:: console

   $ openstack registered limit delete <registered-limit-id> [<registered-limit-id> ...]

View and update quota values for a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To list quotas for a project, run:

.. code-block:: console

   $ openstack limit list --project <project>

.. note::

   This lists project quotas for all services and not just nova.

To list quotas for all projects, you must have a system-scoped authorization
token and run:

.. code-block:: console

   $ openstack limit list

To show details about a quota limit, run:

.. code-block:: console

   $ openstack limit show <limit-id>

To create a quota limit for a project, run:

.. code-block:: console

   $ openstack limit create --service nova --project <project> --resource-limit <value> <resource-name>

To update quotas for a project, run:

.. code-block:: console

   $ openstack limit set --resource-limit <value> <limit-id>

To delete quotas for a project, run:

.. code-block:: console

   $ openstack limit delete <limit-id> [<limit-id> ...]


Migration to unified limits quotas
----------------------------------

There is a `nova-manage limits migrate_to_unified_limits`_ command available to
help with moving from legacy Nova database quotas to Keystone unified limits
quotas. The command will read quota limits from the Nova database and call the
Keystone API to create the corresponding unified limits. Per-user quota limits
will **not** be copied into Keystone because per-user quotas are not supported
in unified limits.

.. _nova-manage limits migrate_to_unified_limits: https://docs.openstack.org/nova/latest/cli/nova-manage.html#limits-migrate-to-unified-limits
