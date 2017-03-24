:tocdepth: 2

===============
 Placement API
===============

.. TODO(cdent) this is a big pile of todo

This is a reference for the Openstack Placement API. To learn more about
Openstack Placement API concepts, please refer to the
`Placement Introduction <http://docs.openstack.org/developer/nova/placement.html>`_.

.. rest_expand_all::

========
Versions
========

List Versions
=============

.. rest_method:: GET /

Fetch information about all known major versions of the placement API,
including information about the minimum and maximum microversions.

.. note:: At this time there is only one major version of the placement API:
          version 1.0.

Normal Response Codes: 200

Response
--------

.. rest_parameters:: parameters.yaml

  - versions: versions
  - id: version_id
  - min_version: version_min
  - max_version: version_max

Response Example
----------------

.. literalinclude:: get-root.json
   :language: javascript

==================
Resource Providers
==================

Resource providers are entities which provide consumable inventory of one or
more classes of resource (such as disk or memory). They can be listed (with
filters), created, updated and deleted.

List Resource Providers
=======================

.. rest_method:: GET /resource_providers

List an optionally filtered collection of resource providers.

Normal Response Codes: 200

Request
-------

Several query parameters are available to filter the returned list of
resource providers. If multiple different parameters are provided, the results
of all filters are merged with a boolean `AND`.

.. rest_parameters:: parameters.yaml

  - resources: resources_query
  - member_of: member_of
  - uuid: resource_provider_uuid_query
  - name: resource_provider_name_query

Response
--------

.. rest_parameters:: parameters.yaml

  - resource_providers: resource_providers
  - generation: resource_provider_generation
  - uuid: resource_provider_uuid
  - links: resource_provider_links
  - name: resource_provider_name


Response Example
----------------

.. literalinclude:: get-resource_providers.json
   :language: javascript
