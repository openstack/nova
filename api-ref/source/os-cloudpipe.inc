.. -*- rst -*-

==========================
 Cloudpipe (os-cloudpipe)
==========================

Manages virtual VPNs for projects.

List Cloudpipes
===============

.. rest_method:: GET /v2.1/{tenant_id}/os-cloudpipe

Lists cloudpipes.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Cloudpipes: JSON request**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-get-resp.json
   :language: javascript

Create Cloudpipe
================

.. rest_method:: POST /v2.1/{tenant_id}/os-cloudpipe

Creates a cloudpipe.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - project_id: project_id

**Example Create Cloudpipe: JSON request**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-create-req.json
   :language: javascript

Response
--------

**Example Create Cloudpipe: JSON request**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-create-resp.json
   :language: javascript

Update Cloudpipe
================

.. rest_method:: POST /v2.1/{tenant_id}/os-cloudpipe/configure-project

Updates the virtual private network (VPN) IP address and port for a cloudpipe instance.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - vpn_ip: vpn_ip
  - vpn_port: vpn_port

**Example Update Cloudpipe: JSON request**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-update-req.json
   :language: javascript

Response
--------

