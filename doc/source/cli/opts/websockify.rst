.. option:: --cert CERT

    Path to SSL certificate file.

.. option:: --daemon

    Run as a background process.

.. option:: --key KEY

    SSL key file (if separate from cert).

.. option:: --nodaemon

    The inverse of :option:`--daemon`.

.. option:: --nosource_is_ipv6

    The inverse of :option:`--source_is_ipv6`.

.. option:: --nossl_only

    The inverse of :option:`--ssl_only`.

.. option:: --record RECORD

    Filename that will be used for storing websocket frames received and sent
    by a proxy service (like VNC, spice, serial) running on this host. If this
    is not set, no recording will be done.

.. option:: --source_is_ipv6

    Set to True if source host is addressed with IPv6.

.. option:: --ssl_only

    Disallow non-encrypted connections.

.. option:: --web WEB

    Path to directory with content which will be served by a web server.
