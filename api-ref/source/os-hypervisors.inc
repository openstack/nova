.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

==============================
 Hypervisors (os-hypervisors)
==============================

Lists all hypervisors, shows summary statistics for all hypervisors over
all compute nodes, shows details for a hypervisor, and shows the uptime
for a hypervisor.

List Hypervisors
================

.. rest_method:: GET /v2.1/{tenant_id}/os-hypervisors

Lists hypervisors.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Hypervisors: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-list-resp.json
   :language: javascript

List Hypervisors Details
========================

.. rest_method:: GET /v2.1/{tenant_id}/os-hypervisors/detail

Lists hypervisors details.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Hypervisors Details: JSON request**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-detail-resp.json
   :language: javascript

Show Hypervisor Statistics
==========================

.. rest_method:: GET /v2.1/{tenant_id}/os-hypervisors/statistics

Shows summary statistics for all hypervisors over all compute nodes.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example Show Hypervisor Statistics: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-statistics-resp.json
   :language: javascript

Show Hypervisor Details
=======================

.. rest_method:: GET /v2.1/{tenant_id}/os-hypervisors/{hypervisor_id}

Shows details for a hypervisor.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - hypervisor_id: hypervisor_id

Response
--------

**Example Show Hypervisor Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-show-resp.json
   :language: javascript

Show Hypervisor Uptime
======================

.. rest_method:: GET /v2.1/{tenant_id}/os-hypervisors/{hypervisor_id}/uptime

Shows the uptime for a hypervisor.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - hypervisor_id: hypervisor_id

Response
--------

**Example Show Hypervisor Uptime: JSON response**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-uptime-resp.json
   :language: javascript

Search Hypervisor
=================

.. rest_method:: GET /v2.1/{tenant_id}/os-hypervisors/{hypervisor_id}/search

Search hypervisor by given hypervisor id.

Normal response code: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - hypervisor_id: hypervisor_id

Response
--------

**Example Search Hypervisor: JSON request**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-search-resp.json
   :language: javascript

List Hypervisor Servers
=======================

.. rest_method:: GET /v2.1/{tenant_id}/os-hypervisors/{hypervisor_id}/servers

List all servers belong to given hypervisor.

Normal response code: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - hypervisor_id: hypervisor_id

Response
--------

**Example List Hypervisor Servers: JSON request**

.. literalinclude:: ../../doc/api_samples/os-hypervisors/hypervisors-with-servers-resp.json
   :language: javascript
