===============
nova-novncproxy
===============

-------------------------------------------------------
Websocket novnc Proxy for OpenStack Nova noVNC consoles
-------------------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

  nova-novncproxy [options]

Description
===========

`nova-novncproxy` is a server daemon that serves the Nova noVNC Websocket Proxy
service, which provides a websocket proxy that is compatible with OpenStack
Nova noVNC consoles.

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
