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
