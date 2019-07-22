.. -*- rst -*-
.. NOTE(gmann): These APIs are deprecated so do not update this
   file even body, example or parameters are not complete.

===================================================
 Project networks (os-tenant-networks) (DEPRECATED)
===================================================

.. warning::

   These APIs are proxy calls to the Network service. Nova has
   deprecated all the proxy APIs and users should use the native APIs
   instead. These will fail with a 404 starting from microversion 2.36.
   See: `Relevant Network APIs
   <https://docs.openstack.org/api-ref/network/v2/#networks>`__.

Creates, lists, shows information for, and deletes project networks.

List Project Networks
=====================

.. rest_method:: GET /os-tenant-networks

Lists all project networks.

Policy defaults enable only users with the administrative role or
the owner of the network to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example List Project Networks: JSON response**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-list-res.json
   :language: javascript

Create Project Network
======================

.. rest_method:: POST /os-tenant-networks

.. note::
    This API is only implemented for the nova-network service and will result
    in a 503 error response if the cloud is using the Neutron networking
    service. Use the Neutron ``networks`` API to create a new network.

Creates a project network.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409), serviceUnavailable(503)

**Example Create Project Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-post-req.json
   :language: javascript

Response
--------

**Example Create Project Network: JSON response**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-post-res.json
   :language: javascript

Show Project Network Details
============================

.. rest_method:: GET /os-tenant-networks/{network_id}

Shows details for a project network.

Policy defaults enable only users with the administrative role or
the owner of the network to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - network_id: network_id

Response
--------

**Example Show Project Network Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-post-res.json
   :language: javascript

Delete Project Network
======================

.. rest_method:: DELETE /os-tenant-networks/{network_id}

.. note::
    This API is only implemented for the nova-network service and will result
    in a 500 error response if the cloud is using the Neutron networking
    service. Use the Neutron ``networks`` API to delete an existing network.

Deletes a project network.

Policy defaults enable only users with the administrative role or
the owner of the network to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - network_id: network_id

Response
--------

There is no body content for the response of a successful DELETE query.
