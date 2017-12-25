======
Usages
======

Represent the consumption of resources for a project and user.

.. note:: Usages API requests are available starting from version 1.9.

List usages
===========

Return a report of usage information for resources associated with the
project identified by `project_id` and user identified by
`user_id`. The value is a dictionary of resource classes paired with
the sum of the allocations of that resource class for provided
parameters.

.. rest_method:: GET /usages

Normal Response Codes: 200

Error response codes: badRequest(400)

Request
-------

.. rest_parameters:: parameters.yaml

  - project_id: project_id
  - user_id: user_id

Response
--------

.. rest_parameters:: parameters.yaml

  - usages: resources

Response Example
----------------

.. literalinclude:: ./samples/usages/get-usages.json
   :language: javascript
