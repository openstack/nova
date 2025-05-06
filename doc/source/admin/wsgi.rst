Using WSGI with Nova
====================

.. versionchanged:: 33.0.0

    Removed support for the eventlet server scripts, ``nova-api``,
    ``nova-api-metadata`` and ``nova-api-os-compute``. Only WSGI-based
    deployments are supported going forward and it is no longer possible to run
    the compute API and metadata APIs in the same process, as it was with the
    eventlet scripts.

.. versionchanged:: 33.0.0

    Removed the ``nova-api-wsgi`` and ``nova-metadata-wsgi`` WSGI scripts
    previously provided by Nova. Deployment tooling should instead reference
    the Python module paths for these services, ``nova.wsgi.osapi_compute`` and
    ``nova.wsgi.metadata``, if their chosen WSGI server supports this
    (gunicorn, uWSGI) or implement a ``.wsgi`` script themselves if not
    (mod_wsgi).

Nova provides two APIs: a compute API (a.k.a. the REST API) and a
:doc:`metadata API </user/metadata>`. Both of these APIs are implemented as
generic Python HTTP servers that implement WSGI_ and are expected to be
deployed using a server with WSGI support.

To facilitate this, Nova provides a WSGI module for each API that provide the
``application`` object that most WSGI servers require. These can be found at
``nova.wsgi.osapi_compute`` and ``nova.wsgi.metadata`` for the compute API and
the metadata API, respectively. The ``application`` objects are automatically
configured with configuration from ``nova.conf`` and ``api-paste.ini`` by
default, and the the config files and config directory can be overridden via
the ``OS_NOVA_CONFIG_FILES`` and ``OS_NOVA_CONFIG_DIR`` environment variables.

.. note::

    File paths listed in ``OS_NOVA_CONFIG_FILES`` are relative to
    ``OS_NOVA_CONFIG_DIR`` and delimited by ``;``.

DevStack deploys the compute and metadata APIs behind Apache using uwsgi_ via
mod_proxy_uwsgi_. Inspecting the configuration created there can provide some
guidance on one option for managing the WSGI scripts. It is important to
remember, however, that one of the major features of using WSGI is that there
are many different ways to host a WSGI application. Different servers make
different choices about performance and configurability. It is up to you, as a
deployer, to choose an appropriate server for your deployment.

.. _WSGI: https://www.python.org/dev/peps/pep-3333/
.. _uwsgi: https://uwsgi-docs.readthedocs.io/
.. _mod_proxy_uwsgi: http://uwsgi-docs.readthedocs.io/en/latest/Apache.html#mod-proxy-uwsgi
