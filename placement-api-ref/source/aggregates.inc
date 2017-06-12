============================
Resource provider aggregates
============================

Each resource provider can be associated with one or more other
resource providers in groups called aggregates. API calls in this
section are used to list and update the aggregates that are associated
with one resource provider.

.. note:: Placement aggregates are *not* the same as Nova host
   aggregates and should not be considered equivalent.

The primary differences between Nova's host aggregates and placement
aggregates are the following:

* In Nova, a host aggregate associates a *nova-compute service* with
  other nova-compute services. Placement aggregates are not specific
  to a nova-compute service and are, in fact, not
  compute-specific at all. A resource provider in the Placement API is
  generic, and placement aggregates are simply groups of generic
  resource providers. This is an important difference especially for
  Ironic, which when used with Nova, has many Ironic baremetal nodes
  attached to a single nova-compute service. In the Placement API,
  each Ironic baremetal node is its own resource provider and can
  therefore be associated to other Ironic baremetal nodes via a
  placement aggregate association.
* In Nova, a host aggregate may have *metadata* key/value pairs
  attached to it. All nova-compute services associated with a Nova
  host aggregate share the same metadata. Placement aggregates have no
  such metadata because placement aggregates *only* represent the
  grouping of resource providers. In the Placement API, resource
  providers are individually decorated with *traits* that provide
  qualitative information about the resource provider.
* In Nova, a host aggregate dictates the *availability zone* within
  which one or more nova-compute services reside. Placement aggregates
  have no concept of an availability zone.

.. note:: Aggregates API requests are availiable starting from version 1.1.

List resource provider aggregates
=================================

.. rest_method:: GET /resource_providers/{uuid}/aggregates

Return a list of aggregates associated with the resource provider
identified by `{uuid}`.

Normal Response Codes: 200

Error response codes: itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response
--------

.. rest_parameters:: parameters.yaml

  - aggregates: aggregates

Response Example
----------------

.. literalinclude:: get-aggregates.json
   :language: javascript

Update resource provider aggregates
===================================

Associate a list of aggregates with the resource provider identified by `{uuid}`.

.. rest_method:: PUT /resource_providers/{uuid}/aggregates

Normal Response Codes: 200

Error response codes: badRequest(400), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - aggregates: aggregates

Request example
---------------

.. literalinclude:: update-aggregates-request.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - aggregates: aggregates

Response Example
----------------

.. literalinclude:: update-aggregates.json
   :language: javascript
