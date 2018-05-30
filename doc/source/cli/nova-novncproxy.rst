===============
nova-novncproxy
===============

-------------------------------------------------------
Websocket novnc Proxy for OpenStack Nova noVNC consoles
-------------------------------------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-novncproxy [options]

Description
===========

:program:`nova-novncproxy` is a server daemon that serves the Nova noVNC
Websocket Proxy service, which provides a websocket proxy that is compatible
with OpenStack Nova noVNC consoles.

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

* :nova-doc:`OpenStack Nova <>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
