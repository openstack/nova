.. -*- rst -*-

==============
 Service URLs
==============

All API calls described throughout the rest of this document require
authentication with the OpenStack Identity service. After authentication,
a base ``service url`` can be extracted from the Identity token of type
``compute``. This ``service url`` will be the root url that every API call
uses to build a full path.

For instance, if the ``service url`` is
``http://mycompute.pvt/compute/v2.1`` then the full API call for
``/servers`` is ``http://mycompute.pvt/compute/v2.1/servers``.

Depending on the deployment, the Compute ``service url`` might be http or
https, a custom port, a custom path, and include your tenant id. The
only way to know the urls for your deployment is by using the service
catalog. The Compute URL should never be hard coded in applications,
even if they are only expected to work at a single site. It should
always be discovered from the Identity token.

As such, for the rest of this document we will be using short hand
where ``GET /servers`` really means ``GET
{your_compute_service_url}/servers``.
