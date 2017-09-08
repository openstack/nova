===================
nova-api-os-compute
===================

------------------------------------------
Server for the Nova OpenStack Compute APIs
------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

  nova-api-os-compute  [options]

Description
===========

`nova-api-os-compute` is a server daemon that serves the Nova OpenStack Compute
API

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

* `OpenStack Nova <https://docs.openstack.org/nova/latest/>`__
* `Using WSGI with Nova <https://docs.openstack.org/nova/latest/user/wsgi.html>`__

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
