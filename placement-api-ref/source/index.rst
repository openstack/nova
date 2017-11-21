:tocdepth: 2

===============
 Placement API
===============

This is a reference for the Openstack Placement API. To learn more about
Openstack Placement API concepts, please refer to the
`Placement Introduction <https://docs.openstack.org/nova/latest/user/placement.html>`_.

The Placement API uses JSON for data exchange.  As such, the ``Content-Type``
header for APIs sending data payloads in the request body (i.e. ``PUT`` and
``POST``) must be set to ``application/json`` unless otherwise noted.

.. rest_expand_all::

.. include:: root.inc
.. include:: resource_providers.inc
.. include:: resource_provider.inc
.. include:: resource_classes.inc
.. include:: resource_class.inc
.. include:: inventories.inc
.. include:: inventory.inc
.. include:: aggregates.inc
.. include:: traits.inc
.. include:: resource_provider_traits.inc
.. include:: allocations.inc
.. include:: resource_provider_allocations.inc
.. include:: usages.inc
.. include:: resource_provider_usages.inc
.. include:: allocation_candidates.inc
