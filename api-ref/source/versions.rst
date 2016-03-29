==============
 API Versions
==============

Concepts
========

In order to bring new features to users over time, the Nova API
supports versioning. There are 2 kinds of versions in Nova ''major
versions'' as defined by dedicated urls. There are also
''microversions'' which can be requested through use of the
``OpenStack-API-Version`` header.

List All Major Versions
=======================

.. rest_method:: GET /

Normal Response Codes: 200 300

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - x-openstack-request-id: request_id

Response Example
~~~~~~~~~~~~~~~~

.. literalinclude:: /../../doc/api_samples/versions/versions-get-resp.json
   :language: javascript


Show Details of 2.1 API
=======================

.. rest_method:: GET /v2.1

Normal Response Codes: 200 300

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - x-openstack-request-id: request_id

Response Example
~~~~~~~~~~~~~~~~

.. literalinclude:: /../../doc/api_samples/versions/v21-version-get-resp.json
   :language: javascript
