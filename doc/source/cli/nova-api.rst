========
nova-api
========

-------------------------------------
Server for the OpenStack Compute APIs
-------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

  nova-api  [options]

Description
===========

`nova-api` is a server daemon that serves the metadata and compute APIs in
separate greenthreads

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
