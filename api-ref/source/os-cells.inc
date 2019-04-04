.. -*- rst -*-

==============================
 Cells (os-cells, capacities)
==============================

Adds neighbor cells, lists neighbor cells, and shows the capabilities of
the local cell. By default, only administrators can manage cells.

.. warning::

   These APIs refer to a Cells v1 deployment which was deprecated in the 16.0.0
   Pike release. These are not used with Cells v2 which is required beginning
   with the 15.0.0 Ocata release where all Nova deployments consist of at least
   one Cells v2 cell.
   They were removed in the 20.0.0 Train release.

List Cells
==========

.. rest_method:: GET /os-cells

Lists cells.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - limit: limit_simple
  - offset: offset_simple

Response
--------

**Example List Cells: JSON response**

.. literalinclude:: ../../doc/api_samples/os-cells/cells-list-resp.json
   :language: javascript

Create Cell
===========

.. rest_method:: POST /os-cells

Create a new cell.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
gone(410), notImplemented(501)

Capacities
==========

.. rest_method:: GET /os-cells/capacities

Retrieve capacities.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
gone(410), notImplemented(501)

List Cells With Details
=======================

.. rest_method:: GET /os-cells/detail

Lists cells with details of capabilities.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: limit_simple
  - offset: offset_simple

Info For This Cell
==================

.. rest_method:: GET /os-cells/info

Retrieve info about the current cell.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
gone(410), notImplemented(501)

Show Cell Data
==============

.. rest_method:: GET /os-cells/{cell_id}

Shows data for a cell.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - cell_id: cell_id

Response
--------

**Example Show Cell Data: JSON response**

.. literalinclude:: ../../doc/api_samples/os-cells/cells-get-resp.json
   :language: javascript

Update a Cell
=============

.. rest_method:: PUT /os-cells/{cell_id}


Update an existing cell.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410), notImplemented(501)

Delete a Cell
=============

.. rest_method:: DELETE /os-cells/{cell_id}

Remove a cell.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410), notImplemented(501)

Show Cell Capacities
====================

.. rest_method:: GET /os-cells/{cell_id}/capacities

Shows capacities for a cell.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - cell_id: cell_id

Response
--------

**Example Show Cell Capacities: JSON response**

.. literalinclude:: ../../doc/api_samples/os-cells/cells-capacities-resp.json
   :language: javascript
