.. -*- rst -*-

==============
 Service URLs
==============

All API calls through the rest of this document require authentication
with the OpenStack Identity service. They also required a base
``service url`` that is extracted from the Identity token of type
``compute``. This will be the root url that every call below will be
added to build a full path.

For instance, if the ``service url`` is
``http://mycompute.pvt/compute/v2.1`` then the full API call for
``/servers`` is ``http://mycompute.pvt/compute/v2.1/servers``.

Depending on the deployment the compute service url might be http or
https, a custom port, a custom path, and include your tenant id. The
only way to know the urls for your deployment is by using the service
catalog. The compute URL should never be hard coded in applications,
even if they are only expected to work at a single site. It should
always be discovered from the Identity token.

As such, for the rest of this document we will be using short hand
where ``GET /servers`` really means ``GET
{your_compute_service_url}/servers``.
