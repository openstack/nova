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
