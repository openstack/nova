..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

========
 Quotas
========

Nova uses a quota system for setting limits on resources such as number of
instances or amount of CPU that a specific project or user can use.

Starting in the 16.0.0 Pike release the quota calculation system in nova was
overhauled and the old reserve/commit/rollback flow was changed to `count
resource usage`_ at the point of whatever operation is being performed, such
as creating or resizing a server. A check will be performed by counting
current usage for the relevant resource and then if
:oslo.config:option:`quota.recheck_quota` is True (it is by default) another
check will be performed to ensure the initial check is still valid.

By default resource usage is counted using the API and cell databases but
nova can be configured to count some resource usage without using the cell
databases, see `Quota usage from placement`_ for details.

Quota limits and usage can be retrieved via the `limits`_ REST API. Quota
limits can be set per-tenant using the `quota sets`_ REST API or per class
(all tenants) using the `quota class sets`_ API.

.. _count resource usage: https://specs.openstack.org/openstack/nova-specs/specs/pike/implemented/cells-count-resources-to-check-quota-in-api.html
.. _limits: https://docs.openstack.org/api-ref/compute/#limits-limits
.. _quota sets: https://docs.openstack.org/api-ref/compute/#quota-sets-os-quota-sets
.. _quota class sets: https://docs.openstack.org/api-ref/compute/#quota-class-sets-os-quota-class-sets

Checking quota
==============

When calculating limits for a given resource and tenant, the following
checks are made in order:

* Depending on the resource, is there a tenant-specific limit on the resource
  in either the `quotas` or `project_user_quotas` tables in the database? If
  so, use that as the limit. You can create these resources by doing::

   openstack quota set --instances 5 <project>

* Check to see if there is a hard limit for the given resource in the
  `quota_classes` table in the database for the `default` quota class. If so,
  use that as the limit. You can modify the default quota limit for a resource
  by doing::

   openstack quota set --class --instances 5 default

* If the above does not provide a resource limit, then rely on the
  :oslo.config:group:`quota` configuration options for the default limit.

.. note:: The API sets the limit in the `quota_classes` table. Once a default
   limit is set via the `default` quota class, that takes precedence over
   any changes to that resource limit in the configuration options. In other
   words, once you've changed things via the API, you either have to keep those
   synchronized with the configuration values or remove the default limit from
   the database manually as there is no REST API for removing quota class
   values from the database.

.. _quota-usage-from-placement:

Quota usage from placement
==========================

Starting in the Train (20.0.0) release, it is possible to configure quota usage
counting of cores and ram from the placement service and instances from
instance mappings in the API database instead of counting resources from cell
databases. This makes quota usage counting resilient in the presence of `down
or poor-performing cells`_.

Quota usage counting from placement is opt-in via configuration option:

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

.. _down or poor-performing cells: https://docs.openstack.org/api-guide/compute/down_cells.html


Known issues
============

If not :ref:`counting quota usage from placement <quota-usage-from-placement>`
it is possible for down or poor performing cells to impact quota calculations.
See the :ref:`cells documentation <cells-counting-quotas>` for details.

Future plans
============

Hierarchical quotas
-------------------

There has long been a desire to support hierarchical or nested quotas
leveraging support in the identity service for hierarchical projects.
See the `unified limits`_ spec for details.

.. _unified limits: https://review.opendev.org/#/c/602201/
