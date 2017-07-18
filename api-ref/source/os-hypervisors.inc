.. -*- rst -*-

.. _os-hypervisors:

==============================
 Hypervisors (os-hypervisors)
==============================

Lists all hypervisors, shows summary statistics for all hypervisors over
all compute nodes, shows details for a hypervisor, shows the uptime
for a hypervisor, lists all servers on hypervisors that match the given
``hypervisor_hostname_pattern`` or searches for hypervisors by the given
``hypervisor_hostname_pattern``.

List Hypervisors
================

.. rest_method:: GET /os-hypervisors

Lists hypervisors.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through
the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: hypervisor_limit
  - marker: hypervisor_marker
  - marker: hypervisor_marker_uuid
  - hypervisor_hostname_pattern: hypervisor_hostname_pattern_query
  - with_servers: hypervisor_with_servers_query

Response
--------

.. rest_parameters:: parameters.yaml

  - hypervisors: hypervisors
  - hypervisor_hostname: hypervisor_hostname
  - id: hypervisor_id_body
  - id: hypervisor_id_body_uuid
  - state: hypervisor_state
  - status: hypervisor_status
  - hypervisor_links: hypervisor_links
  - servers: hypervisor_servers
  - servers.uuid: hypervisor_servers_uuid
  - servers.name: hypervisor_servers_name

**Example List Hypervisors (v2.33): JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/v2.33/hypervisors-list-resp.json
   :language: javascript

**Example List Hypervisors With Servers (v2.53): JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/v2.53/hypervisors-with-servers-resp.json
   :language: javascript

List Hypervisors Details
========================

.. rest_method:: GET /os-hypervisors/detail

Lists hypervisors details.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through
the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: hypervisor_limit
  - marker: hypervisor_marker
  - marker: hypervisor_marker_uuid
  - hypervisor_hostname_pattern: hypervisor_hostname_pattern_query
  - with_servers: hypervisor_with_servers_query

Response
--------

.. rest_parameters:: parameters.yaml

  - hypervisors: hypervisors
  - cpu_info: cpu_info
  - current_workload: current_workload
  - status: hypervisor_status
  - state: hypervisor_state
  - disk_available_least: disk_available_least
  - host_ip: host_ip
  - free_disk_gb: hypervisor_free_disk_gb
  - free_ram_mb: free_ram_mb
  - hypervisor_hostname: hypervisor_hostname
  - hypervisor_type: hypervisor_type_body
  - hypervisor_version: hypervisor_version
  - id: hypervisor_id_body
  - id: hypervisor_id_body_uuid
  - local_gb: local_gb
  - local_gb_used: local_gb_used
  - memory_mb: memory_mb
  - memory_mb_used: memory_mb_used
  - running_vms: running_vms
  - servers: hypervisor_servers
  - servers.uuid: hypervisor_servers_uuid
  - servers.name: hypervisor_servers_name
  - service: hypervisor_service
  - service.host: host_name_body
  - service.id: service_id_body_2_52
  - service.id: service_id_body_2_53
  - service.disable_reason: service_disable_reason
  - vcpus: hypervisor_vcpus
  - vcpus_used: hypervisor_vcpus_used
  - hypervisor_links: hypervisor_links

**Example List Hypervisors Details (v2.33): JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/v2.33/hypervisors-detail-resp.json
   :language: javascript

**Example List Hypervisors Details (v2.53): JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/v2.53/hypervisors-detail-resp.json
   :language: javascript

Show Hypervisor Statistics
==========================

.. rest_method:: GET /os-hypervisors/statistics

Shows summary statistics for all enabled hypervisors over all compute nodes.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through
the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - hypervisor_statistics: hypervisor_statistics
  - count: hypervisor_count
  - current_workload: current_workload
  - disk_available_least: disk_available_least
  - free_disk_gb: hypervisor_free_disk_gb
  - free_ram_mb: free_ram_mb
  - local_gb: local_gb
  - local_gb_used: local_gb_used
  - memory_mb: memory_mb
  - memory_mb_used: memory_mb_used
  - running_vms: running_vms_total
  - vcpus: hypervisor_vcpus
  - vcpus_used: hypervisor_vcpus_used

**Example Show Hypervisor Statistics: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-statistics-resp.json
   :language: javascript

Show Hypervisor Details
=======================

.. rest_method:: GET /os-hypervisors/{hypervisor_id}

Shows details for a given hypervisor.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through
the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - hypervisor_id: hypervisor_id
  - hypervisor_id: hypervisor_id_uuid
  - with_servers: hypervisor_with_servers_query

Response
--------

.. rest_parameters:: parameters.yaml

  - hypervisor: hypervisor
  - cpu_info: cpu_info
  - state: hypervisor_state
  - status: hypervisor_status
  - current_workload: current_workload
  - disk_available_least: disk_available_least
  - host_ip: host_ip
  - free_disk_gb: hypervisor_free_disk_gb
  - free_ram_mb: free_ram_mb
  - hypervisor_hostname: hypervisor_hostname
  - hypervisor_type: hypervisor_type_body
  - hypervisor_version: hypervisor_version
  - id: hypervisor_id_body
  - id: hypervisor_id_body_uuid
  - local_gb: local_gb
  - local_gb_used: local_gb_used
  - memory_mb: memory_mb
  - memory_mb_used: memory_mb_used
  - running_vms: running_vms
  - servers: hypervisor_servers
  - servers.uuid: hypervisor_servers_uuid
  - servers.name: hypervisor_servers_name
  - service: hypervisor_service
  - service.host: host_name_body
  - service.id: service_id_body_2_52
  - service.id: service_id_body_2_53
  - service.disable_reason: service_disable_reason
  - vcpus: hypervisor_vcpus
  - vcpus_used: hypervisor_vcpus_used

**Example Show Hypervisor Details (v2.28): JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/v2.28/hypervisors-show-resp.json
   :language: javascript

**Example Show Hypervisor Details With Servers (v2.53): JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/v2.53/hypervisors-show-with-servers-resp.json
   :language: javascript

Show Hypervisor Uptime
======================

.. rest_method:: GET /os-hypervisors/{hypervisor_id}/uptime

Shows the uptime for a given hypervisor.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through
the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - hypervisor_id: hypervisor_id
  - hypervisor_id: hypervisor_id_uuid

Response
--------

.. rest_parameters:: parameters.yaml

  - hypervisor: hypervisor
  - hypervisor_hostname: hypervisor_hostname
  - id: hypervisor_id_body
  - id: hypervisor_id_body_uuid
  - state: hypervisor_state
  - status: hypervisor_status
  - uptime: uptime

**Example Show Hypervisor Uptime: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-uptime-resp.json
   :language: javascript

**Example Show Hypervisor Uptime (v2.53): JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/v2.53/hypervisors-uptime-resp.json
   :language: javascript

Search Hypervisor
=================

.. rest_method:: GET /os-hypervisors/{hypervisor_hostname_pattern}/search
   max_version: 2.52

Search hypervisor by a given hypervisor host name or portion of it.

.. warning:: This API is deprecated starting with microversion 2.53. Use
    `List Hypervisors`_ with the ``hypervisor_hostname_pattern`` query
    parameter with microversion 2.53 and later.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through
the ``policy.json`` file.

Normal response code: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - hypervisor_hostname_pattern: hypervisor_hostname_pattern

Response
--------

.. rest_parameters:: parameters.yaml

  - hypervisors: hypervisors
  - hypervisor_hostname: hypervisor_hostname
  - id: hypervisor_id_body_no_version
  - state: hypervisor_state
  - status: hypervisor_status

**Example Search Hypervisor: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-search-resp.json
   :language: javascript

List Hypervisor Servers
=======================

.. rest_method:: GET /os-hypervisors/{hypervisor_hostname_pattern}/servers
   max_version: 2.52

List all servers belong to each hypervisor whose host name is matching
a given hypervisor host name or portion of it.

.. warning:: This API is deprecated starting with microversion 2.53. Use
    `List Hypervisors`_ with the ``hypervisor_hostname_pattern`` and
    ``with_servers`` query parameters with microversion 2.53 and later.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through
the ``policy.json`` file.

Normal response code: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - hypervisor_hostname_pattern: hypervisor_hostname_pattern

Response
--------

.. rest_parameters:: parameters.yaml

  - hypervisors: hypervisors
  - hypervisor_hostname: hypervisor_hostname
  - id: hypervisor_id_body_no_version
  - state: hypervisor_state
  - status: hypervisor_status
  - servers: servers
  - servers.uuid: server_uuid
  - servers.name: server_name

**Example List Hypervisor Servers: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-with-servers-resp.json
   :language: javascript
