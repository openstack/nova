============================
Request and response formats
============================

The OpenStack Compute API supports JSON request and response formats.

Request format
~~~~~~~~~~~~~~

Use the ``Content-Type`` request header to specify the request format.
This header is required for operations that have a request body.

The syntax for the ``Content-Type`` header is:

.. code::

    Content-Type: application/FORMAT

Where ``FORMAT`` is ``json``.

Response format
~~~~~~~~~~~~~~~

Use one of the following methods to specify the response format:

``Accept`` header
The syntax for the ``Accept`` header is:

    .. code::

        Accept: application/FORMAT

Where *``FORMAT``* is ``json`` and the default format is ``json``.

Query extension
Add a ``.json`` extension to the request URI. For example, the ``.json`` extension in the following list servers URI request specifies that the response body is to be returned in JSON format:

    **GET** *``publicURL``*/servers.json

If you do not specify a response format, JSON is the default.

Request and response examples
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can serialize a response in a different format from the request
format.

The examples below show a request body in JSON format.

.. note:: Though you may find outdated documents with XML examples, XML support
   in requests and responses has been deprecated for the Compute API v2
   (stable) and v2.1 (experimental).

**Example: JSON request with headers**

| POST /v2/010101/servers HTTP/1.1
|  Host: servers.api.openstack.org
|  Content-Type: application/json
|  Accept: application/xml
|  X-Auth-Token: eaaafd18-0fed-4b3a-81b4-663c99ec1cbb

.. code::

    {
        "server": {
            "name": "server-test-1",
            "imageRef": "b5660a6e-4b46-4be3-9707-6b47221b454f",
            "flavorRef": "2",
            "max_count": 1,
            "min_count": 1,
            "networks": [
                {
                    "uuid": "d32019d3-bc6e-4319-9c1d-6722fc136a22"
                }
            ],
            "security_groups": [
                {
                    "name": "default"
                },
                {
                    "name": "another-secgroup-name"
                }
            ]
        }
    }

