REST API Version History
~~~~~~~~~~~~~~~~~~~~~~~~

This documents the changes made to the REST API with every
microversion change. The description for each version should be a
verbose one which has enough information to be suitable for use in
user documentation.

1.0 (Maximum in Newton)
-----------------------

This is the initial version of the placement REST API that was released in
Nova 14.0.0 (Newton). This contains the following routes:

* /resource_providers
* /resource_providers/allocations
* /resource_providers/inventories
* /resource_providers/usages
* /allocations

1.1
___

The 1.1 version adds support for associating aggregates with
resource providers with ``GET`` and ``PUT`` methods on one new
route:

* /resource_providers/{uuid}/aggregates

1.2 Custom resource classes
---------------------------

Placement API version 1.2 adds basic operations allowing an admin to create,
list and delete custom resource classes.

The following new routes are added:

* GET /resource_classes: return all resource classes
* POST /resource_classes: create a new custom resource class
* PUT /resource_classes/{name}: update name of custom resource class
* DELETE /resource_classes/{name}: deletes a custom resource class
* GET /resource_classes/{name}: get a single resource class

Custom resource classes must begin with the prefix "CUSTOM\_" and contain only
the letters A through Z, the numbers 0 through 9 and the underscore "\_"
character.
