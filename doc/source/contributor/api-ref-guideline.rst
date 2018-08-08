=======================
API reference guideline
=======================

The API reference should be updated when compute or placement APIs are modified
(microversion is bumped, etc.).
This page describes the guideline for updating the API reference.

API reference
=============

* `Compute API reference <https://developer.openstack.org/api-ref/compute/>`_
* `Placement API reference <https://developer.openstack.org/api-ref/placement/>`_

The guideline to write the API reference
========================================

The API reference consists of the following files.

Compute API reference
---------------------

* API reference text: ``api-ref/source/*.inc``
* Parameter definition: ``api-ref/source/parameters.yaml``
* JSON request/response samples: ``doc/api_samples/*``

Placement API reference
-----------------------

* API reference text: ``placement-api-ref/source/*.inc``
* Parameter definition: ``placement-api-ref/source/parameters.yaml``
* JSON request/response samples: ``placement-api-ref/source/samples/*``

Structure of inc file
---------------------

Each REST API is described in the text file (\*.inc).
The structure of inc file is as follows:

- Title

  - API Name

    - REST Method

      - URL
      - Description
      - Normal status code
      - Error status code
      - Request

        - Parameters
        - JSON request body example (if exists)
      - Response

        - Parameters
        - JSON response body example (if exists)
  - API Name (Next)

    - ...

REST Method
-----------

The guideline for describing HTTP methods is described in this section.
All supported methods by resource should be listed in the API reference.

The order of methods
~~~~~~~~~~~~~~~~~~~~

Methods have to be sorted by each URI in the following order:

1. GET
2. POST
3. PUT
4. PATCH (unused by Nova)
5. DELETE

And sorted from broadest to narrowest. So for /severs it would be:

1. GET /servers
2. POST /servers
3. GET /servers/details
4. GET /servers/{server_id}
5. PUT /servers/{server_id}
6. DELETE /servers/{server_id}

Method titles spelling and case
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The spelling and the case of method names in the title have to match
what is in the code. For instance, the title for the section on method
"Get Rdp Console" should be "Get Rdp Console (os-getRDPConsole Action)"
NOT "Get Rdp Console (Os-Getrdpconsole Action)"

Response codes
~~~~~~~~~~~~~~

The normal response codes (20x) and error response codes
have to be listed. The order of response codes should be in ascending order.
The description of typical error response codes are as follows:

.. list-table:: Error response codes
   :header-rows: 1

   * - Response codes
     - Description
   * - 400
     - badRequest(400)
   * - 401
     - unauthorized(401)
   * - 403
     - forbidden(403)
   * - 404
     - itemNotFound(404)
   * - 409
     - conflict(409)
   * - 410
     - gone(410)
   * - 501
     - notImplemented(501)
   * - 503
     - serviceUnavailable(503)

Parameters
----------

Parameters need to be defined by 2 subsections.
The one is in the 'Request' subsection, the other is in the 'Response'
subsection. The queries, request headers and attributes go in the 'Request'
subsection and response headers and attributes go in the 'Response'
subsection.

The order of parameters in each API
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The request and response parameters have to be listed in the following order
in each API in the text file.

1. Header
2. Path
3. Query
4. Body

   a. Top level object (i.e. server)
   b. Required fields
   c. Optional fields
   d. Parameters added in microversions (by the microversion they were added)

Parameter type
~~~~~~~~~~~~~~

The parameters are defined in the parameter file (``parameters.yaml``).
The type of parameters have to be one of followings:

* ``array``

  It is a list.

* ``boolean``
* ``float``
* ``integer``
* ``none``

  The value is always ``null`` in a response or
  should be ``null`` in a request.

* ``object``

  The value is dict.

* ``string``

  If the value can be specified by multiple types, specify one type
  in the file and mention the other types in the description.

Required or optional
~~~~~~~~~~~~~~~~~~~~

In the parameter file, define the ``required`` field in each parameter.

.. list-table::
  :widths: 15 85

  * - ``true``
    - The parameter must be specified in the request, or
      the parameter always appears in the response.
  * - ``false``
    - It is not always necessary to specify the parameter in the request, or
      the parameter does not appear in the response in some cases.
      e.g. A config option defines whether the parameter appears
      in the response or not. A parameter appears when administrators call
      but does not appear when non-admin users call.

If a parameter must be specified in the request or always appears
in the response in the micoversion added or later,
the parameter must be defined as required (``true``).

The order of parameters in the parameter file
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The order of parameters in the parameter file has to be kept as follows:

1. By in type

   a. Header
   b. Path
   c. Query
   d. Body

2. Then alphabetical by name

Example
-------

.. TODO::

  The guideline for request/response JSON bodies should be added.

Body
----

.. TODO::

  The guideline for the introductory text and the context for the resource
  in question should be added.

Reference
=========

* `Verifying the Nova API Ref <https://wiki.openstack.org/wiki/NovaAPIRef>`_
* `The description for Parameters whose values are null <http://lists.openstack.org/pipermail/openstack-dev/2017-January/109868.html>`_
* `The definition of "Optional" parameter <http://lists.openstack.org/pipermail/openstack-dev/2017-July/119239.html>`_
