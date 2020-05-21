===============
nova-novncproxy
===============

.. program:: nova-novncproxy

Synopsis
========

::

  nova-novncproxy [<options>...]

Description
===========

:program:`nova-novncproxy` is a server daemon that serves the Nova noVNC
Websocket Proxy service, which provides a websocket proxy that is compatible
with OpenStack Nova noVNC consoles.

Options
=======

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: Websockify options

.. include:: opts/websockify.rst

.. rubric:: VNC options

.. option:: --vnc-auth_schemes VNC_AUTH_SCHEMES

    The authentication schemes to use with the compute node. Control what RFB
    authentication schemes are permitted for connections between the proxy and
    the compute host. If multiple schemes are enabled, the first matching
    scheme will be used, thus the strongest schemes should be listed first.

.. option:: --vnc-novncproxy_host VNC_NOVNCPROXY_HOST

    IP address that the noVNC console proxy should bind to. The VNC proxy is an
    OpenStack component that enables compute service users to access their
    instances through VNC clients. noVNC provides VNC support through a
    websocket-based client. This option sets the private address to which the
    noVNC console proxy service should bind to.

.. option:: --vnc-novncproxy_port VNC_NOVNCPROXY_PORT

    Port that the noVNC console proxy should bind to. The VNC proxy is an
    OpenStack component that enables compute service users to access their
    instances through VNC clients. noVNC provides VNC support through a
    websocket-based client. This option sets the private port to which the
    noVNC console proxy service should bind to.

.. option:: --vnc-vencrypt_ca_certs VNC_VENCRYPT_CA_CERTS

    The path to the CA certificate PEM file The fully qualified path to a PEM
    file containing one or more x509 certificates for the certificate
    authorities used by the compute node VNC server.

.. option:: --vnc-vencrypt_client_cert VNC_VENCRYPT_CLIENT_CERT

    The path to the client key file (for x509) The fully qualified path to a
    PEM file containing the x509 certificate which the VNC proxy server
    presents to the compute node during VNC authentication.

.. option:: --vnc-vencrypt_client_key VNC_VENCRYPT_CLIENT_KEY

    The path to the client certificate PEM file (for x509) The fully qualified
    path to a PEM file containing the private key which the VNC proxy server
    presents to the compute node during VNC authentication.

.. rubric:: Debugger options

.. include:: opts/debugger.rst

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

:doc:`nova-serialproxy(1) <nova-serialproxy>`,
:doc:`nova-spicehtml5proxy(1) <nova-spicehtml5proxy>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
