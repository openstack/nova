========
Reshaper
========

.. note:: Reshaper requests are available starting from version 1.30.

Reshaper
========

Atomically migrate resource provider inventories and associated allocations.
This is used when some of the inventory needs to move from one resource
provider to another, such as when a class of inventory moves from a parent
provider to a new child provider.

.. note:: This is a special operation that should only be used in rare cases
          of resource provider topology changing when inventory is in use.
          Only use this if you are really sure of what you are doing.

.. rest_method:: POST /reshaper

Normal Response Codes: 204

Error Response Codes: badRequest(400), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - inventories: reshaper_inventories
  - inventories.{resource_provider_uuid}.resource_provider_generation: resource_provider_generation
  - inventories.{resource_provider_uuid}.inventories: inventories
  - allocations: reshaper_allocations
  - allocations.{consumer_uuid}.allocations: allocations_dict_empty
  - allocations.{consumer_uuid}.allocations.{resource_provider_uuid}.resources: resources
  - allocations.{consumer_uuid}.project_id: project_id_body
  - allocations.{consumer_uuid}.user_id: user_id_body
  - allocations.{consumer_uuid}.consumer_generation: consumer_generation

Request Example
---------------

.. literalinclude:: ./samples/reshaper/post-reshaper-1.30.json
   :language: javascript

No body content is returned on a successful POST.
