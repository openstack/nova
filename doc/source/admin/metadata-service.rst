================
Metadata service
================

.. note::

   This section provides deployment information about the metadata service. For
   end-user information about the metadata service and instance metadata in
   general, refer to the :ref:`user guide <metadata-service>`.

The metadata service provides a way for instances to retrieve instance-specific
data. Instances access the metadata service at ``http://169.254.169.254``. The
metadata service supports two sets of APIs - an OpenStack metadata API and an
EC2-compatible API - and also exposes vendordata and user data. Both the
OpenStack metadata and EC2-compatible APIs are versioned by date.

The metadata service can be run globally, as part of the :program:`nova-api`
application, or on a per-cell basis, as part of the standalone
:program:`nova-api-metadata` application. A detailed comparison is provided in
the :ref:`cells V2 guide <cells-v2-layout-metadata-api>`.

.. versionchanged:: 19.0.0

   The ability to run the nova metadata API service on a per-cell basis was
   added in Stein. For versions prior to this release, you should not use the
   standalone :program:`nova-api-metadata` application for multiple cells.

Guests access the service at ``169.254.169.254`` or at ``fe80::a9fe:a9fe``.

.. versionchanged:: 22.0.0

    Starting with the Victoria release the metadata service is accessible
    over IPv6 at the link-local address ``fe80::a9fe:a9fe``.

The networking service,
neutron, is responsible for intercepting these requests and adding HTTP headers
which uniquely identify the source of the request before forwarding it to the
metadata API server. For the Open vSwitch and Linux Bridge backends provided
with neutron, the flow looks something like so:

#. Instance sends a HTTP request for metadata to ``169.254.169.254``.

#. This request either hits the router or DHCP namespace depending on the route
   in the instance

#. The metadata proxy service in the namespace adds the following info to the
   request:

   - Instance IP (``X-Forwarded-For`` header)
   - Router or Network-ID (``X-Neutron-Network-Id`` or ``X-Neutron-Router-Id``
     header)

#. The metadata proxy service sends this request to the metadata agent (outside
   the namespace) via a UNIX domain socket.

#. The :program:`neutron-metadata-agent` application forwards the request to the
   nova metadata API service by adding some new headers (instance ID and Tenant
   ID) to the request.

This flow may vary if a different networking backend is used.

Neutron and nova must be configured to communicate together with a shared
secret. Neutron uses this secret to sign the Instance-ID header of the metadata
request to prevent spoofing. This secret is configured through the
:oslo.config:option:`neutron.metadata_proxy_shared_secret` config option in nova
and the equivalent ``metadata_proxy_shared_secret`` config option in neutron.

Configuration
-------------

The :program:`nova-api` application accepts the following metadata
service-related options:

- :oslo.config:option:`enabled_apis`
- :oslo.config:option:`enabled_ssl_apis`
- :oslo.config:option:`neutron.service_metadata_proxy`
- :oslo.config:option:`neutron.metadata_proxy_shared_secret`
- :oslo.config:option:`api.metadata_cache_expiration`
- :oslo.config:option:`api.use_forwarded_for`
- :oslo.config:option:`api.local_metadata_per_cell`
- :oslo.config:option:`api.dhcp_domain`

.. note::

    This list excludes configuration options related to the vendordata feature.
    Refer to :doc:`vendordata feature documentation </admin/vendordata>` for
    information on configuring this.

For example, to configure the :program:`nova-api` application to serve the
metadata API, without SSL, using the ``StaticJSON`` vendordata provider, add the
following to a :file:`nova-api.conf` file:

.. code-block:: ini

    [DEFAULT]
    enabled_apis = osapi_compute,metadata
    enabled_ssl_apis =
    metadata_listen = 0.0.0.0
    metadata_listen_port = 0
    metadata_workers = 4

    [neutron]
    service_metadata_proxy = True

    [api]
    dhcp_domain =
    metadata_cache_expiration = 15
    use_forwarded_for = False
    local_metadata_per_cell = False
    vendordata_providers = StaticJSON
    vendordata_jsonfile_path = /etc/nova/vendor_data.json

.. note::

    This does not include configuration options that are not metadata-specific
    but are nonetheless required, such as
    :oslo.config:option:`api.auth_strategy`.

Configuring the application to use the ``DynamicJSON`` vendordata provider is
more involved and is not covered here.

The :program:`nova-api-metadata` application accepts almost the same options:

- :oslo.config:option:`neutron.service_metadata_proxy`
- :oslo.config:option:`neutron.metadata_proxy_shared_secret`
- :oslo.config:option:`api.metadata_cache_expiration`
- :oslo.config:option:`api.use_forwarded_for`
- :oslo.config:option:`api.local_metadata_per_cell`
- :oslo.config:option:`api.dhcp_domain`

.. note::

    This list excludes configuration options related to the vendordata feature.
    Refer to :doc:`vendordata feature documentation </admin/vendordata>` for
    information on configuring this.

For example, to configure the :program:`nova-api-metadata` application to serve
the metadata API, without SSL, add the following to a :file:`nova-api.conf`
file:

.. code-block:: ini

    [DEFAULT]
    metadata_listen = 0.0.0.0
    metadata_listen_port = 0
    metadata_workers = 4

    [neutron]
    service_metadata_proxy = True

    [api]
    dhcp_domain =
    metadata_cache_expiration = 15
    use_forwarded_for = False
    local_metadata_per_cell = False

.. note::

    This does not include configuration options that are not metadata-specific
    but are nonetheless required, such as
    :oslo.config:option:`api.auth_strategy`.

For information about configuring the neutron side of the metadata service,
refer to the :neutron-doc:`neutron configuration guide
<configuration/metadata-agent.html>`


Config drives
-------------

Config drives are special drives that are attached to an instance when it boots.
The instance can mount this drive and read files from it to get information that
is normally available through the metadata service. For more information, refer
to :doc:`/admin/config-drive` and the :ref:`user guide <metadata-config-drive>`.


Vendordata
----------

Vendordata provides a way to pass vendor or deployment-specific information to
instances. For more information, refer to :doc:`/admin/vendordata` and the
:ref:`user guide <metadata-vendordata>`.


User data
---------

User data is a blob of data that the user can specify when they launch an
instance. For more information, refer to :ref:`the user guide
<metadata-userdata>`.
