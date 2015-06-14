========
Versions
========

The OpenStack Compute API uses both a URI and a MIME type versioning
scheme. In the URI scheme, the first element of the path contains the
target version identifier (e.g. https://servers.api.openstack.org/
v2.0/...). The MIME type versioning scheme uses HTTP content negotiation
where the ``Accept`` or ``Content-Type`` headers contains a MIME type
that identifies the version (application/vnd.openstack.compute.v2+json).
A version MIME type is always linked to a base MIME type, such as
application/json. If conflicting versions are specified using both an HTTP
header and a URI, the URI takes precedence.

**Example: Request with MIME type versioning**

.. code::

    GET /214412/images HTTP/1.1
    Host: servers.api.openstack.org
    Accept: application/vnd.openstack.compute.v2+json
    X-Auth-Token: eaaafd18-0fed-4b3a-81b4-663c99ec1cbb


**Example: Request with URI versioning**

.. code::

    GET /v2/214412/images HTTP/1.1
    Host: servers.api.openstack.org
    Accept: application/json
    X-Auth-Token: eaaafd18-0fed-4b3a-81b4-663c99ec1cbb


Permanent Links
~~~~~~~~~~~~~~~

The MIME type versioning approach allows for the creating of permanent
links, because the version scheme is not specified in the URI path:
https://api.servers.openstack.org/224532/servers/123.

If a request is made without a version specified in the URI or via HTTP
headers, then a multiple-choices response (300) follows that provides
links and MIME types to available versions.


**Example: Multiple choices: JSON response**

.. code::

    {
       "choices":[
          {
             "id":"v1.0",
             "status":"DEPRECATED",
             "links":[
                {
                   "rel":"self",
                   "href":"http://servers.api.openstack.org/v1.0/1234/servers/52415800-8b69-11e0-9b19-734f6af67565"
                }
             ],
             "media-types":[
                {
                   "base":"application/json",
                   "type":"application/vnd.openstack.compute.v1.0+json"
                }
             ]
          },
          {
             "id":"v2",
             "status":"CURRENT",
             "links":[
                {
                   "rel":"self",
                   "href":"http://servers.api.openstack.org/v2/1234/servers/52415800-8b69-11e0-9b19-734f6af67565"
                }
             ],
             "media-types":[
                {
                   "base":"application/json",
                   "type":"application/vnd.openstack.compute.v2+json"
                }
             ]
          }
       ]
    }


New features and functionality that do not break API-compatibility are
introduced in the current version of the API as extensions and the URI and MIME
types remain unchanged. Features or functionality changes that would necessitate a break in API-compatibility require a new version, which results
in URI and MIME type version being updated accordingly. When new API versions
are released, older versions are marked as ``DEPRECATED``. Providers should
work with developers and partners to ensure there is adequate time to
migrate to the new version before deprecated versions are discontinued.

Your application can programmatically determine available API versions
by performing a **GET** on the root URL (i.e. with the version and
everything to the right of it truncated) returned from the
authentication system.

You can also obtain additional information about a specific version by
performing a **GET** on the base version URL (such as,
``https://servers.api.openstack.org/v2/``). Version request URLs must
always end with a trailing slash (``/``). If you omit the slash, the
server might respond with a 302 redirection request. Format extensions
can be placed after the slash (such as,
``https://servers.api.openstack.org/v2/.json``).

.. note:: This special case does not hold true for other API requests. In
   general, requests such as ``/servers.json`` and ``/servers/.json`` are
   handled equivalently.

For examples of the list versions and get version details requests and
responses, see `*API versions*
<http://developer.openstack.org/api-ref-compute-v2.html#compute_versions>`__.

The detailed version response contains pointers to both a human-readable
and a machine-processable description of the API service. The
machine-processable description is written in the Web Application
Description Language (WADL).

