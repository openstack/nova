============================
Request and response formats
============================

The OpenStack Compute API only supports JSON request and response
formats, with a mime-type of ``application/json``. As there is only
one supported content type, all content is assumed to be
``application/json`` in both request and response formats.

Request and response example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The example below shows a request body in JSON format:

**Example: JSON request with headers**

.. code::

   POST /v2.1/servers HTTP/1.1
   Host: servers.api.openstack.org
   X-Auth-Token: eaaafd18-0fed-4b3a-81b4-663c99ec1cbb

.. code:: JSON

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
