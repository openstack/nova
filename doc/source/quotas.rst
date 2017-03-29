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

Quotas are enforced by making a claim, or reservation, on resources when a
request is made, such as creating a new server. If the claim fails, the request
is rejected. If the reservation succeeds then the operation progresses until
such a point that the reservation is either converted into usage (the operation
was successful) or rolled back (the operation failed).

Typically the quota reservation is made in the nova-api service and the usage
or rollback is performed in the nova-compute service, at least when dealing
with a server creation or move operation.

Quota limits and usage can be retrieved via the ``limits`` REST API.

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

* If the above does not provide a resource limit, then rely on the ``quota_*``
  configuration options for the default limit.

.. note:: The API sets the limit in the `quota_classes` table. Once a default
   limit is set via the `default` quota class, that takes precedence over
   any changes to that resource limit in the configuration options. In other
   words, once you've changed things via the API, you either have to keep those
   synchronized with the configuration values or remove the default limit from
   the database manually as there is no REST API for removing quota class
   values from the database.


Known issues
============

TODO: talk about quotas getting out of sync and `how to recover`_

.. _how to recover: https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/refresh-quotas-usage.html


Future plans
============

TODO: talk about quotas in the  `resource counting spec`_ and `nested quotas`_

.. _resource counting spec: https://specs.openstack.org/openstack/nova-specs/specs/ocata/approved/cells-count-resources-to-check-quota-in-api.html
.. _nested quotas: https://specs.openstack.org/openstack/nova-specs/specs/mitaka/approved/nested-quota-driver-api.html
