.. -*- rst -*-

======================================
 Cloudpipe (os-cloudpipe) (DEPRECATED)
======================================

.. warning::

   This API only works with ``nova-network`` which is
   deprecated in favor of Neutron. It should be avoided
   in any new applications. It was removed in the 16.0.0
   Pike release.

Manages virtual VPNs for projects.

List Cloudpipes
===============

.. rest_method:: GET /os-cloudpipe

Lists cloudpipes.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound (404)

Response
--------

.. rest_parameters:: parameters.yaml

  - cloudpipes: cloudpipes
  - created_at: created
  - instance_id: instance_id_cloudpipe
  - internal_ip: fixed_ip
  - project_id: project_id_instance_action
  - public_ip: vpn_public_ip_resp
  - public_port: vpn_public_port_resp
  - state: vpn_state

**Example List Cloudpipes: JSON response**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-get-resp.json
   :language: javascript

Create Cloudpipe
================

.. rest_method:: POST /os-cloudpipe

Creates a cloudpipe.

Normal response codes: 200

Error response codes: badRequest(400),unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - cloudpipe: cloudpipe
  - project_id: project_id

**Example Create Cloudpipe: JSON request**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - instance_id: instance_id_cloudpipe

**Example Create Cloudpipe: JSON response**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-create-resp.json
   :language: javascript

Update Cloudpipe
================

.. rest_method:: PUT /os-cloudpipe/configure-project

Updates the virtual private network (VPN) IP address and port for a cloudpipe instance.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - configure_project: configure_project_cloudpipe
  - vpn_ip: vpn_public_ip
  - vpn_port: vpn_public_port

**Example Update Cloudpipe: JSON request**

.. literalinclude:: ../../doc/api_samples/os-cloudpipe/cloud-pipe-update-req.json
   :language: javascript

Response
--------

There is no body content for the response of a successful PUT request
