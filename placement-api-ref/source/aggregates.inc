============================
Resource provider aggregates
============================

Each resource provider can be associated with one or more other
resource providers in groups called aggregates. API calls in this
section are used to list and update the aggregates that are associated
with one resource provider.

Provider aggregates are used for modeling relationships among providers.
Examples may include:

* A shared storage pool providing DISK_GB resources to compute node providers
  that provide VCPU and MEMORY_MB resources.
* Affinity/anti-affinity relationships such as physical location, power failure
  domains, or other reliability/availability constructs.
* Groupings of compute host providers *corresponding to* Nova host aggregates
  or availability zones.

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
  which one or more nova-compute services reside. While placement aggregates
  may be used to *model* availability zones, they have no inherent concept
  thereof.

.. note:: Aggregates API requests are availiable starting from version 1.1.

List resource provider aggregates
=================================

.. rest_method:: GET /resource_providers/{uuid}/aggregates

Return a list of aggregates associated with the resource provider
identified by `{uuid}`.

Normal Response Codes: 200

Error response codes: itemNotFound(404) if the provider does not exist. (If the
provider has no aggregates, the result is 200 with an empty aggregate list.)

Request
-------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path

Response (microversions 1.1 - 1.18)
-----------------------------------

.. rest_parameters:: parameters.yaml

  - aggregates: aggregates

Response Example (microversions 1.1 - 1.18)
-------------------------------------------

.. literalinclude:: ./samples/aggregates/get-aggregates.json
   :language: javascript

Response (microversions 1.19 - )
--------------------------------

.. rest_parameters:: parameters.yaml

  - aggregates: aggregates
  - resource_provider_generation: resource_provider_generation_v1_19

Response Example (microversions 1.19 - )
----------------------------------------

.. literalinclude:: ./samples/aggregates/get-aggregates-1.19.json
   :language: javascript

Update resource provider aggregates
===================================

Associate a list of aggregates with the resource provider identified by `{uuid}`.

.. rest_method:: PUT /resource_providers/{uuid}/aggregates

Normal Response Codes: 200

Error response codes: badRequest(400), itemNotFound(404), conflict(409)

Request (microversion 1.1 - 1.18)
---------------------------------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - aggregates: aggregates

Request example (microversion 1.1 - 1.18)
-----------------------------------------

.. literalinclude:: ./samples/aggregates/update-aggregates-request.json
   :language: javascript

Request (microversion 1.19 - )
---------------------------------

.. rest_parameters:: parameters.yaml

  - uuid: resource_provider_uuid_path
  - aggregates: aggregates
  - resource_provider_generation: resource_provider_generation_v1_19

Request example (microversion 1.19 - )
-----------------------------------------

.. literalinclude:: ./samples/aggregates/update-aggregates-request-1.19.json
   :language: javascript

Response (microversion 1.19 - )
----------------------------------

.. rest_parameters:: parameters.yaml

  - aggregates: aggregates
  - resource_provider_generation: resource_provider_generation_v1_19

Response Example (microversion 1.19 - )
------------------------------------------

.. literalinclude:: ./samples/aggregates/update-aggregates-1.19.json
   :language: javascript
