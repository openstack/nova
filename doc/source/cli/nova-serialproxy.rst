================
nova-serialproxy
================

.. program:: nova-serialproxy

Synopsis
========

::

  nova-serialproxy [<options>...]

Description
===========

:program:`nova-serialproxy` is a server daemon that serves the Nova Serial
Websocket Proxy service, which provides a websocket proxy that is compatible
with OpenStack Nova serial ports.

Options
=======

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: Websockify options

.. include:: opts/websockify.rst

.. rubric:: Serial options

.. option:: --serial_console-serialproxy_host SERIAL_CONSOLE_SERIALPROXY_HOST

    The IP address which is used by the ``nova-serialproxy`` service to listen
    for incoming requests.  The ``nova-serialproxy`` service listens on this IP
    address for incoming connection requests to instances which expose serial
    console.

.. option:: --serial_console-serialproxy_port SERIAL_CONSOLE_SERIALPROXY_PORT

    The port number which is used by the ``nova-serialproxy`` service to
    listen for incoming requests. The ``nova-serialproxy`` service listens on
    this port number for incoming connection requests to instances which expose
    serial console.

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
:doc:`nova-spicehtml5proxy(1) <nova-spicehtml5proxy>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
