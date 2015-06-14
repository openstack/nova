==============
Authentication
==============

Each HTTP request against the OpenStack Compute system requires the
inclusion of specific authentication credentials. A single deployment
may support multiple authentication schemes (OAuth, Basic Auth, Token).
The authentication scheme is provided by the OpenStack Identity service.
You can contact your provider to determine the best way to authenticate against
the Compute API.

.. note:: Some authentication schemes may require that the API operate using
   SSL over HTTP (HTTPS).

