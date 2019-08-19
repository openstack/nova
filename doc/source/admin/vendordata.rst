==========
Vendordata
==========

.. note::

   This section provides deployment information about the vendordata feature.
   For end-user information about the vendordata feature and instance metadata
   in general, refer to the :doc:`user guide </user/metadata>`.

The *vendordata* feature provides a way to pass vendor or deployment-specific
information to instances. This can be accessed by users using :doc:`the metadata
service </admin/metadata-service>` or with :doc:`config drives
</admin/config-drive>`.

There are two vendordata modules provided with nova: ``StaticJSON`` and
``DynamicJSON``.


``StaticJSON``
--------------

The ``StaticJSON`` module includes the contents of a static JSON file loaded
from disk. This can be used for things which don't change between instances,
such as the location of the corporate puppet server. It is the default provider.

Configuration
~~~~~~~~~~~~~

The service you must configure to enable the ``StaticJSON`` vendordata module
depends on how guests are accessing vendordata. If using the metadata service,
configuration applies to either :program:`nova-api` or
:program:`nova-api-metadata`, depending on the deployment, while if using
config drives, configuration applies to :program:`nova-compute`. However,
configuration is otherwise the same and the following options apply:

- :oslo.config:option:`api.vendordata_providers`
- :oslo.config:option:`api.vendordata_jsonfile_path`

Refer to the :doc:`metadata service </admin/metadata-service>` and :doc:`config
drive </admin/config-drive>` documentation for more information on how to
configure the required services.


``DynamicJSON``
---------------

The ``DynamicJSON`` module can make a request to an external REST service to
determine what metadata to add to an instance. This is how we recommend you
generate things like Active Directory tokens which change per instance.

When used, the ``DynamicJSON`` module will make a request to any REST services
listed in the :oslo.config:option:`api.vendordata_dynamic_targets` configuration
option. There can be more than one of these but note that they will be queried
once per metadata request from the instance which can mean a lot of traffic
depending on your configuration and the configuration of the instance.

The following data is passed to your REST service as a JSON encoded POST:

.. list-table::
   :header-rows: 1

   * - Key
     - Description
   * - ``project-id``
     - The ID of the project that owns this instance.
   * - ``instance-id``
     - The UUID of this instance.
   * - ``image-id``
     - The ID of the image used to boot this instance.
   * - ``user-data``
     - As specified by the user at boot time.
   * - ``hostname``
     - The hostname of the instance.
   * - ``metadata``
     - As specified by the user at boot time.

Metadata fetched from the REST service will appear in the metadata service at a
new file called ``vendordata2.json``, with a path (either in the metadata service
URL or in the config drive) like this::

    openstack/latest/vendor_data2.json

For each dynamic target, there will be an entry in the JSON file named after
that target. For example:

.. code-block:: json

    {
        "testing": {
            "value1": 1,
            "value2": 2,
            "value3": "three"
        }
    }

The `novajoin`__ project provides a dynamic vendordata service to manage host
instantiation in an IPA server.

__ https://opendev.org/x/novajoin

Deployment considerations
~~~~~~~~~~~~~~~~~~~~~~~~~

Nova provides authentication to external metadata services in order to provide
some level of certainty that the request came from nova. This is done by
providing a service token with the request -- you can then just deploy your
metadata service with the keystone authentication WSGI middleware. This is
configured using the keystone authentication parameters in the
:oslo.config:group:`vendordata_dynamic_auth` configuration group.

Configuration
~~~~~~~~~~~~~

As with ``StaticJSON``, the service you must configure to enable the
``DynamicJSON`` vendordata module depends on how guests are accessing
vendordata. If using the metadata service, configuration applies to either
:program:`nova-api` or :program:`nova-api-metadata`, depending on the
deployment, while if using config drives, configuration applies to
:program:`nova-compute`. However, configuration is otherwise the same and the
following options apply:

- :oslo.config:option:`api.vendordata_providers`
- :oslo.config:option:`api.vendordata_dynamic_ssl_certfile`
- :oslo.config:option:`api.vendordata_dynamic_connect_timeout`
- :oslo.config:option:`api.vendordata_dynamic_read_timeout`
- :oslo.config:option:`api.vendordata_dynamic_failure_fatal`
- :oslo.config:option:`api.vendordata_dynamic_targets`

Refer to the :doc:`metadata service </admin/metadata-service>` and :doc:`config
drive </admin/config-drive>` documentation for more information on how to
configure the required services.

In addition, there are also many options related to authentication. These are
provided by :keystone-doc:`keystone <>` but are listed below for completeness:

- :oslo.config:option:`vendordata_dynamic_auth.cafile`
- :oslo.config:option:`vendordata_dynamic_auth.certfile`
- :oslo.config:option:`vendordata_dynamic_auth.keyfile`
- :oslo.config:option:`vendordata_dynamic_auth.insecure`
- :oslo.config:option:`vendordata_dynamic_auth.timeout`
- :oslo.config:option:`vendordata_dynamic_auth.collect_timing`
- :oslo.config:option:`vendordata_dynamic_auth.split_loggers`
- :oslo.config:option:`vendordata_dynamic_auth.auth_type`
- :oslo.config:option:`vendordata_dynamic_auth.auth_section`
- :oslo.config:option:`vendordata_dynamic_auth.auth_url`
- :oslo.config:option:`vendordata_dynamic_auth.system_scope`
- :oslo.config:option:`vendordata_dynamic_auth.domain_id`
- :oslo.config:option:`vendordata_dynamic_auth.domain_name`
- :oslo.config:option:`vendordata_dynamic_auth.project_id`
- :oslo.config:option:`vendordata_dynamic_auth.project_name`
- :oslo.config:option:`vendordata_dynamic_auth.project_domain_id`
- :oslo.config:option:`vendordata_dynamic_auth.project_domain_name`
- :oslo.config:option:`vendordata_dynamic_auth.trust_id`
- :oslo.config:option:`vendordata_dynamic_auth.default_domain_id`
- :oslo.config:option:`vendordata_dynamic_auth.default_domain_name`
- :oslo.config:option:`vendordata_dynamic_auth.user_id`
- :oslo.config:option:`vendordata_dynamic_auth.username`
- :oslo.config:option:`vendordata_dynamic_auth.user_domain_id`
- :oslo.config:option:`vendordata_dynamic_auth.user_domain_name`
- :oslo.config:option:`vendordata_dynamic_auth.password`
- :oslo.config:option:`vendordata_dynamic_auth.tenant_id`
- :oslo.config:option:`vendordata_dynamic_auth.tenant_name`

Refer to the :keystone-doc:`keystone documentation </configuration/index.html>`
for information on configuring these.


References
----------

* Michael Still's talk from the Queens summit in Sydney, `Metadata, User Data,
  Vendor Data, oh my!`__
* Michael's blog post on `deploying a simple vendordata service`__ which
  provides more details and sample code to supplement the documentation above.

__ https://www.openstack.org/videos/sydney-2017/metadata-user-data-vendor-data-oh-my
__ https://www.madebymikal.com/nova-vendordata-deployment-an-excessively-detailed-guide/
