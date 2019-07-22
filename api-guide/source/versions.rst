========
Versions
========

The OpenStack Compute API uses both a URI and a MIME type versioning
scheme. In the URI scheme, the first element of the path contains the
target version identifier (e.g. `https://servers.api.openstack.org/
v2.1/`...). The MIME type versioning scheme uses HTTP content negotiation
where the ``Accept`` or ``Content-Type`` headers contains a MIME type
that identifies the version (application/vnd.openstack.compute.v2.1+json).
A version MIME type is always linked to a base MIME type, such as
application/json. If conflicting versions are specified using both an HTTP
header and a URI, the URI takes precedence.

**Example: Request with MIME type versioning**

.. code::

    GET /214412/images HTTP/1.1
    Host: servers.api.openstack.org
    Accept: application/vnd.openstack.compute.v2.1+json
    X-Auth-Token: eaaafd18-0fed-4b3a-81b4-663c99ec1cbb


**Example: Request with URI versioning**

.. code::

    GET /v2.1/214412/images HTTP/1.1
    Host: servers.api.openstack.org
    Accept: application/json
    X-Auth-Token: eaaafd18-0fed-4b3a-81b4-663c99ec1cbb


Permanent Links
~~~~~~~~~~~~~~~

The MIME type versioning approach allows for creating of permanent
links, because the version scheme is not specified in the URI path:
`https://api.servers.openstack.org/224532/servers/123`.

If a request is made without a version specified in the URI or via HTTP
headers, then a multiple-choices response (300) follows that provides
links and MIME types to available versions.


**Example: Multiple choices: JSON response**

.. code::

  {
    "choices": [
        {
            "id": "v2.0",
            "links": [
                {
                    "href": "http://servers.api.openstack.org/v2/7f5b2214547e4e71970e329ccf0b257c/servers/detail",
                    "rel": "self"
                }
            ],
            "media-types": [
                {
                    "base": "application/json",
                    "type": "application/vnd.openstack.compute+json;version=2"
                }
            ],
            "status": "SUPPORTED"
        },
        {
            "id": "v2.1",
            "links": [
                {
                    "href": "http://servers.api.openstack.org/v2.1/7f5b2214547e4e71970e329ccf0b257c/servers/detail",
                    "rel": "self"
                }
            ],
            "media-types": [
                {
                    "base": "application/json",
                    "type": "application/vnd.openstack.compute+json;version=2.1"
                }
            ],
            "status": "CURRENT"
        }
    ]
  }

The API with ``CURRENT`` status is the newest API and continues to be improved by the
Nova project. The API with ``SUPPORTED`` status is the old API, where new features are
frozen. The API with ``DEPRECATED`` status is the API that will be removed in the
foreseeable future. Providers should work with developers and partners to
ensure there is adequate time to migrate to the new version before deprecated
versions are discontinued. For any API which is under development but isn't
released as yet, the API status is ``EXPERIMENTAL``.

Your application can programmatically determine available API versions
by performing a **GET** on the root URL (i.e. with the version and
everything following that truncated) returned from the authentication system.

You can also obtain additional information about a specific version by
performing a **GET** on the base version URL (such as,
`https://servers.api.openstack.org/v2.1/`). Version request URLs must
always end with a trailing slash (`/`). If you omit the slash, the
server might respond with a 302 redirection request.

For examples of the list versions and get version details requests and
responses, see `API versions
<https://docs.openstack.org/api-ref/compute/#api-versions>`__.

The detailed version response contains pointers to both a human-readable
and a machine-processable description of the API service.
