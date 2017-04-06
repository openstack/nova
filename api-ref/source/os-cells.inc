.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification


==============================
 Cells (os-cells, capacities)
==============================

Adds neighbor cells, lists neighbor cells, and shows the capabilities of
the local cell. By default, only administrators can manage cells.

.. note:: These APIs refer to a Cells v1 deployment which is optional and not
  recommended for new deployments of Nova. These are not used with Cells v2
  which is required beginning with the 15.0.0 Ocata release where all Nova
  deployments consist of at least one Cells v2 cell.

List Cells
==========

.. rest_method:: GET /os-cells

Lists cells.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - limit: limit_simple
  - offset: offset_simple

.. TODO(cdent): How do we indicate optionality of a URI parameter?

Response
--------

**Example List Cells: JSON response**

.. literalinclude:: ../../doc/api_samples/os-cells/cells-list-resp.json
   :language: javascript

Create Cell
===========

.. rest_method:: POST /os-cells

Create a new cell.

Normal response code: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
NotImplemented(501)

.. TODO(cdent): need to figure out body stuff for request and response

.. TODO(cdent): need a sample

Capacities
==========

.. rest_method:: GET /os-cells/capacities

Retrieve capacities.

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
NotImplemented(501)

.. TODO(cdent): Need to do more digging, no idea.

List Cells With Details
=======================

.. rest_method:: GET /os-cells/detail

Lists cells with details of capabilities.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: limit_simple
  - offset: offset_simple

Response
--------

**Example List Cells With Details: JSON response**

.. TODO(cdent): This sample was initially list with an empty list of cells.
   The newly listed sample does not yet exist.

.. TODO(cdent):  literal-include: ../../doc/api_samples/os-cells/cells-list-details-resp.json
   :language: javascript

Info For This Cell
==================

.. rest_method:: GET /os-cells/info

Retrieve info about the current cell.

Normal response code: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
NotImplemented(501)

.. TODO(cdent): this is weird, data is structured entirely differently.

Show Cell Data
==============

.. rest_method:: GET /os-cells/{cell_id}

Shows data for a cell.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

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

.. rest_method:: PUT /os-cells/{cell_od}


Update an existing cell.

Normal response code: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

.. TODO(cdent): Figure out what's going on here.

Delete a Cell
=============

.. rest_method:: DELETE /os-cells/{cell_id}

Remove a cell.

Normal response code: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Show Cell Capacities
====================

.. rest_method:: GET /os-cells/{cell_id}/capacities

Shows capacities for a cell.

.. TODO(cdent): What's a capacities.

Normal response codes: 200,501

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), NotImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - cell_id: cell_id

Response
--------

**Example Show Cell Capacities: JSON response**

.. literalinclude:: ../../doc/api_samples/os-cells/cells-capacities-resp.json
   :language: javascript
