=======================
API reference guideline
=======================

The API reference should be updated when compute APIs are modified
(microversion is bumped, etc.).
This page describes the guideline for updating the API reference.

API reference
=============

* `Compute API reference <https://docs.openstack.org/api-ref/compute/>`_

The guideline to write the API reference
========================================

The API reference consists of the following files.

Compute API reference
---------------------

* API reference text: ``api-ref/source/*.inc``
* Parameter definition: ``api-ref/source/parameters.yaml``
* JSON request/response samples: ``doc/api_samples/*``

Structure of inc file
---------------------

Each REST API is described in the text file (\*.inc).
The structure of inc file is as follows:

- Title (Resource name)

  - Introductory text and context

    The introductory text and the context for the resource in question should
    be added. This might include links to the API Concept guide, or building
    other supporting documents to explain a concept (like versioning).

  - API Name

    - REST Method

      - URL
      - Description

        See the `Description`_ section for more details.
      - Response codes
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

Description
-----------

The following items should be described in each API.
Or links to the pages describing them should be added.

* The purpose of the API(s)

  - e.g. Lists, creates, shows details for, updates, and deletes servers.
  - e.g. Creates a server.

* Microversion

  - Deprecated

    - Warning
    - Microversion to start deprecation
    - Alternatives (superseded ways) and
      their links (if document is available)

  - Added

    - Microversion in which the API has been added

  - Changed behavior

    - Microversion to change behavior
    - Explanation of the behavior

  - Changed HTTP response codes

    - Microversion to change the response code
    - Explanation of the response code

* Warning if direct use is not recommended

  - e.g. This is an admin level service API only designed to be used by other
    OpenStack services. The point of this API is to coordinate between Nova
    and Neutron, Nova and Cinder (and potentially future services) on
    activities they both need to be involved in, such as network hotplugging.
    Unless you are writing Neutron or Cinder code you should not be using this API.

* Explanation about statuses of resource in question

  - e.g. The server status.

    - ``ACTIVE``. The server is active.

* Supplementary explanation for parameters

  - Examples of query parameters
  - Parameters that are not specified at the same time
  - Values that cannot be specified.

    - e.g. A destination host is the same host.

* Behavior

  - Config options to change the behavior and the effect
  - Effect to resource status

    - Ephemeral disks, attached volumes, attached network ports and others
    - Data loss or preserve contents

  - Scheduler

    - Whether the scheduler choose a destination host or not

* Sort order of response results

  - Describe sorting order of response results if the API implements the order
    (e.g. The response is sorted by ``created_at`` and ``id``
    in descending order by default)

* Policy

  - Default policy (the admin only, the admin or the owner)
  - How to change the policy

* Preconditions

  - Server status
  - Task state
  - Policy for locked servers
  - Quota
  - Limited support

    - e.g. Only qcow2 is supported

  - Compute driver support

    - If very few compute drivers support the operation, add a warning and
      a link to the support matrix of virt driver.

  - Cases that are not supported

    - e.g. A volume-backed server

* Postconditions

  - If the operation is asynchronous,
    it should be "Asynchronous postconditions".

  - Describe what status/state resource in question becomes by the operation

    - Server status
    - Task state
    - Path of output file

* Troubleshooting

  - e.g. If the server status remains ``BUILDING`` or shows another error status,
    the request failed. Ensure you meet the preconditions then investigate
    the compute node.

* Related operations

  - Operations to be paired

    - e.g. Start and stop

  - Subsequent operation

    - e.g. "Confirm resize" after "Resize" operation

* Performance

  - e.g. The progress of this operation depends on the location of
    the requested image, network I/O, host load, selected flavor, and other
    factors.

* Progress

  - How to get progress of the operation if the operation is asynchronous.

* Restrictions

  - Range that ID is unique

    - e.g. HostId is unique per account and is not globally unique.

* How to avoid errors

  - e.g. The server to get console log from should set
    ``export LC_ALL=en_US.UTF-8`` in order to avoid incorrect unicode error.

* Reference

  - Links to the API Concept guide, or building other supporting documents to
    explain a concept (like versioning).

* Other notices

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

In addition, the following explanations should be described.

- Conditions under which each normal response code is returned
  (If there are multiple normal response codes.)
- Conditions under which each error response code is returned

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

Microversion
~~~~~~~~~~~~

If a parameter is available starting from a microversion,
the microversion must be described by ``min_version``
in the parameter file.
However, if the minimum microversion is the same as a microversion
that the API itself is added, it is not necessary to describe the microversion.

For example::

  aggregate_uuid:
    description: |
      The UUID of the host aggregate.
    in: body
    required: true
    type: string
    min_version: 2.41

This example describes that ``aggregate_uuid`` is available starting
from microversion 2.41.

If a parameter is available up to a microversion,
the microversion must be described by ``max_version``
in the parameter file.

For example::

  security_group_rules:
    description: |
      The number of allowed rules for each security group.
    in: body
    required: false
    type: integer
    max_version: 2.35

This example describes that ``security_group_rules`` is available up to
microversion 2.35 (and has been removed since microversion 2.36).

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

One or more examples should be provided for operations whose request and/or
response contains a payload. The example should describe what the operation
is attempting to do and provide a sample payload for the request and/or
response as appropriate.
Sample files should be created in the ``doc/api_samples`` directory and inlined
by inclusion.

When an operation has no payload in the response, a suitable message should be
included. For example::

  There is no body content for the response of a successful DELETE query.

Examples for multiple microversions should be included in ascending
microversion order.

Reference
=========

* `Verifying the Nova API Ref <https://wiki.openstack.org/wiki/NovaAPIRef>`_
* `The description for Parameters whose values are null <http://lists.openstack.org/pipermail/openstack-dev/2017-January/109868.html>`_
* `The definition of "Optional" parameter <http://lists.openstack.org/pipermail/openstack-dev/2017-July/119239.html>`_
* `How to document your OpenStack API service <https://docs.openstack.org/doc-contrib-guide/api-guides.html#how-to-document-your-openstack-api-service>`_
