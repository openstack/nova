.. -*- rst -*-
.. NOTE(sdague): These APIs are deprecated so do not update this
   file even body, example or parameters are not complete.

=====================================
 Networks (os-networks)  (DEPRECATED)
=====================================

.. warning:: The networks API was designed to work with
             ``nova-network``. Some features are proxied to
             ``neutron`` when appropriate, but as with all translation
             proxies, this is far from perfect compatibility. These
             APIs should be avoided in new applications in favor of
             using ``neutron`` directly. These will fail with a 404
             starting from microversion 2.36.
             See: `Relevant Network APIs
             <https://docs.openstack.org/api-ref/network/v2/#networks>`__.


Creates, lists, shows information for, and deletes networks.

Adds network to a project, disassociates a network from a project, and
disassociates a project from a network.


Associates host with and disassociates host from a network.

List Networks
=============

.. rest_method:: GET /os-networks

Lists networks for the project.

Policy defaults enable all users to perform this operation. Cloud
providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example List Networks: JSON response**

.. literalinclude:: ../../doc/api_samples/os-networks/networks-list-resp.json
   :language: javascript

Create Network
==============

.. rest_method:: POST /os-networks

Creates a network.

Policy defaults enable only users with the administrative role or the
owner of the network to perform this operation. Cloud providers can change
these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409), NotImplemented(501)

Request
-------

**Example Create Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks/network-create-req.json
   :language: javascript

Response
--------

**Example Create Network: JSON response**

.. literalinclude:: ../../doc/api_samples/os-networks/network-create-resp.json
   :language: javascript

Add Network
===========

.. rest_method:: POST /os-networks/add

Adds a network to a project.

Policy defaults enable only users with the administrative role to perform
this operation. Cloud providers can change these permissions through the
``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), NotImplemented(501)

Request
-------

**Example Add Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks/network-add-req.json
   :language: javascript

Response
--------

Show Network Details
====================

.. rest_method:: GET /os-networks/{network_id}

Shows details for a network.

Policy defaults enable all users to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - network_id: network_id

Response
--------

**Example Show Network Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-networks/network-show-resp.json
   :language: javascript

Delete Network
==============

.. rest_method:: DELETE /os-networks/{network_id}

Deletes a network.

Policy defaults enable only users with the administrative role or the
owner of the network to perform this operation. Cloud providers can change
these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - network_id: network_id

Response
--------

There is no body content for the response of a successful DELETE query.

Associate Host (DEPRECATED)
===========================

.. rest_method:: POST /os-networks/{network_id}/action

.. warning::
   This API is only available with ``nova-network`` which is
   deprecated. It should be avoided in any new applications.

Associates a network with a host.

Specify the ``associate_host`` action in the request body.

Policy defaults enable only users with the administrative role or the owner
of the network to perform this operation. Cloud providers can change these
permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - network_id: network_id
  - associate_host: associate_host

**Example Associate Host to Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks-associate/network-associate-host-req.json
   :language: javascript

Response
--------

There is no body content for the response of a successful POST query.

Disassociate Network (DEPRECATED)
=================================

.. rest_method:: POST /os-networks/{network_id}/action

.. warning::
   This API is only available with ``nova-network`` which is
   deprecated. It should be avoided in any new applications.

Disassociates a network from a project. You can then reuse the network.

Specify the ``disassociate`` action in the request body.

Policy defaults enable only users with the administrative role or the
owner of the network to perform this operation. Cloud providers can change
these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - network_id: network_id

**Example Disassociate Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks-associate/network-disassociate-req.json
   :language: javascript

Response
--------

There is no body content for the response of a successful POST query.

Disassociate Host (DEPRECATED)
==============================

.. rest_method:: POST /os-networks/{network_id}/action

.. warning::
   This API is only available with ``nova-network`` which is
   deprecated. It should be avoided in any new applications.

Disassociates a host from a network.

Specify the ``disassociate_host`` action in the request body.

Policy defaults enable only users with the administrative role or the
owner of the network to perform this operation. Cloud providers can change
these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - network_id: network_id

**Example Disassociate Host from Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks-associate/network-disassociate-host-req.json
   :language: javascript

Response
--------

There is no body content for the response of a successful POST query.


Disassociate Project (DEPRECATED)
=================================

.. rest_method:: POST /os-networks/{network_id}/action

.. warning::
   This API is only available with ``nova-network`` which is
   deprecated. It should be avoided in any new applications.

Disassociates a project from a network.

Specify the ``disassociate_project`` action in the request body.

Policy defaults enable only users with the administrative role or the
owner of the network to perform this operation. Cloud providers can change
these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - network_id: network_id

**Example Disassociate Project from Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks-associate/network-disassociate-project-req.json
   :language: javascript

Response
--------

There is no body content for the response of a successful POST query.
