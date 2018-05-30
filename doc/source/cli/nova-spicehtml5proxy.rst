====================
nova-spicehtml5proxy
====================

-------------------------------------------------------
Websocket Proxy for OpenStack Nova SPICE HTML5 consoles
-------------------------------------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-spicehtml5proxy [options]

Description
===========

:program:`nova-spicehtml5proxy` is a server daemon that serves the Nova SPICE
HTML5 Websocket Proxy service, which provides a websocket proxy that is
compatible with OpenStack Nova SPICE HTML5 consoles.

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
