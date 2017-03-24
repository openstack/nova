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
