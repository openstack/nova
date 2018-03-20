================
nova-serialproxy
================

------------------------------------------------------
Websocket serial Proxy for OpenStack Nova serial ports
------------------------------------------------------

:Author: openstack@lists.launchpad.net
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-serialproxy [options]

Description
===========

`nova-serialproxy` is a server daemon that serves the Nova Serial Websocket
Proxy service, which provides a websocket proxy that is compatible with
OpenStack Nova serial ports.

Options
=======

**General options**

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/policy.json``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

* `OpenStack Nova <https://docs.openstack.org/nova/latest/>`__

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
