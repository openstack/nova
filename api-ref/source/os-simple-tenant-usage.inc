.. -*- rst -*-

========================================
 Usage reports (os-simple-tenant-usage)
========================================

Reports usage statistics of compute and storage resources periodically
for an individual tenant or all tenants. The usage statistics will include
all instances' CPU, memory and local disk during a specific period.

Microversion 2.40 added pagination (and ``next`` links) to the usage
statistics via optional ``limit`` and ``marker`` query parameters. If
``limit`` isn't provided, the configurable ``max_limit`` will be used which
currently defaults to 1000. Older microversions will not accept these new
paging query parameters, but they will start to silently limit by
``max_limit``.

.. code-block:: none

    /os-simple-tenant-usage?limit={limit}&marker={instance_uuid}
    /os-simple-tenant-usage/{tenant_id}?limit={limit}&marker={instance_uuid}

.. note::

   A tenant's usage statistics may span multiple pages when the number of
   instances exceeds ``limit``, and API consumers will need to stitch together
   the aggregate results if they still want totals for all instances in a
   specific time window, grouped by tenant.

List Tenant Usage Statistics For All Tenants
============================================

.. rest_method:: GET /os-simple-tenant-usage

Lists usage statistics for all tenants.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - detailed: detailed_simple_tenant_usage
  - end: end_simple_tenant_usage
  - start: start_simple_tenant_usage
  - limit: usage_limit
  - marker: usage_marker

Response
--------

.. rest_parameters:: parameters.yaml

  - tenant_usages: tenant_usages
  - start: start_simple_tenant_usage_body
  - stop: stop_simple_tenant_usage
  - tenant_id: tenant_id_body
  - total_hours: total_hours
  - total_local_gb_usage: total_local_gb_usage
  - total_memory_mb_usage: total_memory_mb_usage
  - total_vcpus_usage: total_vcpus_usage
  - server_usages: server_usages_optional
  - server_usages.ended_at: ended_at_optional
  - server_usages.flavor: flavor_name_optional
  - server_usages.hours: hours_optional
  - server_usages.instance_id: server_id_optional
  - server_usages.local_gb: local_gb_simple_tenant_usage_optional
  - server_usages.memory_mb: memory_mb_simple_tenant_usage_optional
  - server_usages.name: server_name_optional
  - server_usages.started_at: started_at_optional
  - server_usages.state: vm_state_optional
  - server_usages.tenant_id: tenant_id_optional
  - server_usages.uptime: uptime_simple_tenant_usage_optional
  - server_usages.vcpus: vcpus_optional
  - tenant_usages_links: usage_links

**Example List Tenant Usage For All Tenants (v2.40): JSON response**

If the ``detailed`` query parameter is not specified or
is set to other than 1 (e.g. ``detailed=0``), the response is as follows:

.. literalinclude:: ../../doc/api_samples/os-simple-tenant-usage/v2.40/simple-tenant-usage-get.json
   :language: javascript

If the ``detailed`` query parameter is set to one (``detailed=1``),
the response includes ``server_usages`` information for each tenant.
The response is as follows:

.. literalinclude:: ../../doc/api_samples/os-simple-tenant-usage/v2.40/simple-tenant-usage-get-detail.json
   :language: javascript

Show Usage Statistics For Tenant
================================

.. rest_method:: GET /os-simple-tenant-usage/{tenant_id}

Shows usage statistics for a tenant.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - end: end_simple_tenant_usage
  - start: start_simple_tenant_usage
  - limit: usage_limit
  - marker: usage_marker

Response
--------

.. rest_parameters:: parameters.yaml

  - tenant_usage: tenant_usage
  - server_usages: server_usages
  - server_usages.ended_at: ended_at
  - server_usages.flavor: flavor_name
  - server_usages.hours: hours
  - server_usages.instance_id: server_id
  - server_usages.local_gb: local_gb_simple_tenant_usage
  - server_usages.memory_mb: memory_mb_simple_tenant_usage
  - server_usages.name: server_name
  - server_usages.started_at: started_at
  - server_usages.state: OS-EXT-STS:vm_state
  - server_usages.tenant_id: tenant_id_body
  - server_usages.uptime: uptime_simple_tenant_usage
  - server_usages.vcpus: vcpus
  - start: start_simple_tenant_usage_body
  - stop: stop_simple_tenant_usage
  - tenant_id: tenant_id_body
  - total_hours: total_hours
  - total_local_gb_usage: total_local_gb_usage
  - total_memory_mb_usage: total_memory_mb_usage
  - total_vcpus_usage: total_vcpus_usage
  - tenant_usage_links: usage_links

**Example Show Usage Details For Tenant (v2.40): JSON response**

.. literalinclude:: ../../doc/api_samples/os-simple-tenant-usage/v2.40/simple-tenant-usage-get-specific.json
   :language: javascript
