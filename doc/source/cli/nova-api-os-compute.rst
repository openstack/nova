===================
nova-api-os-compute
===================

------------------------------------------
Server for the Nova OpenStack Compute APIs
------------------------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-api-os-compute  [options]

Description
===========

:program:`nova-api-os-compute` is a server daemon that serves the Nova
OpenStack Compute API.

Options
=======

**General options**

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/api-paste.ini``
* ``/etc/nova/policy.json``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

* :nova-doc:`OpenStack Nova <>`
* :nova-doc:`Using WSGI with Nova <user/wsgi.html>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
