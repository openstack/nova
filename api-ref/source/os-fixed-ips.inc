.. -*- rst -*-

=========================
 Fixed IPs (os-fixed-ips)
=========================

.. warning::

   These APIs only work with **nova-network** which is deprecated.
   These will fail with a 404 starting from microversion 2.36.
   They were removed in the 18.0.0 Rocky release.

Shows data for a fixed IP, such as host name, CIDR, and address. Also,
reserves and releases a fixed IP address.

Show Fixed Ip Details
=====================

.. rest_method:: GET /os-fixed-ips/{fixed_ip}

Shows details for a fixed IP address.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410)

Request
-------

.. rest_parameters:: parameters.yaml

  - fixed_ip: fixed_ip_path

Response
--------

.. rest_parameters:: parameters.yaml

  - fixed_ip: fixed_ip_obj
  - address: ip_address
  - cidr: cidr
  - host: fixed_ip_host
  - hostname: fixed_ip_hostname
  - reserved: reserved_fixedip


**Example Show Fixed Ip Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-fixed-ips/fixedips-get-resp.json
   :language: javascript

Reserve Or Release A Fixed Ip
=============================

.. rest_method:: POST /os-fixed-ips/{fixed_ip}/action

Reserves or releases a fixed IP.

To reserve a fixed IP address, specify ``reserve`` in the request body.
To release a fixed IP address, specify ``unreserve`` in the request body.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410)

Request
-------

.. rest_parameters:: parameters.yaml

  - fixed_ip: fixed_ip_path
  - reserve: action_reserve
  - unreserve: action_unreserve


**Example Reserve Or Release A Fixed Ip: JSON request**

.. literalinclude:: ../../doc/api_samples/os-fixed-ips/fixedip-post-req.json
   :language: javascript

Response
--------

There is no body content for the response of a successful POST operation.
