===========
nova-volume
===========

-------------------
Nova Volume Server
-------------------

:Author: openstack@lists.launchpad.net
:Date:   2012-09-27
:Copyright: OpenStack LLC
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-volume [options]

DESCRIPTION
===========

nova-volume manages creating, attaching, detaching, and persistent storage.

Persistent storage volumes keep their state independent of instances.  You can
attach to an instance, terminate the instance, spawn a new instance (even
one from a different image) and re-attach the volume with the same data
intact.


OPTIONS
=======

 **General options**

FILES
========

* /etc/nova/nova.conf
* /etc/nova/policy.json
* /etc/nova/rootwrap.conf
* /etc/nova/rootwrap.d/

SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__
* `OpenStack Nova <http://nova.openstack.org>`__

BUGS
====

* Nova is sourced in Launchpad so you can view current bugs at `OpenStack Nova <http://nova.openstack.org>`__
