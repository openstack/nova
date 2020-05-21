====================
nova-spicehtml5proxy
====================

.. program:: nova-spicehtml5proxy

Synopsis
========

::

  nova-spicehtml5proxy [<options>...]

Description
===========

:program:`nova-spicehtml5proxy` is a server daemon that serves the Nova SPICE
HTML5 Websocket Proxy service, which provides a websocket proxy that is
compatible with OpenStack Nova SPICE HTML5 consoles.

Options
=======

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: Websockify options

.. include:: opts/websockify.rst

.. rubric:: Spice options

.. option:: --spice-html5proxy_host SPICE_HTML5PROXY_HOST

    IP address or a hostname on which the ``nova-spicehtml5proxy`` service
    listens for incoming requests. This option depends on the ``[spice]
    html5proxy_base_url`` option in ``nova.conf``. The ``nova-spicehtml5proxy``
    service must be listening on a host that is accessible from the HTML5
    client.

.. option:: --spice-html5proxy_port SPICE_HTML5PROXY_PORT

    Port on which the ``nova-spicehtml5proxy`` service listens for incoming
    requests. This option depends on the ``[spice] html5proxy_base_url`` option
    in ``nova.conf``.  The ``nova-spicehtml5proxy`` service must be listening
    on a port that is accessible from the HTML5 client.

.. rubric:: Debugger options

.. include:: opts/debugger.rst

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

:doc:`nova-novncproxy(1) <nova-novncproxy>`,
:doc:`nova-serialproxy(1) <nova-serialproxy>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
