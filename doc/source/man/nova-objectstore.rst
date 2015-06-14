================
nova-objectstore
================

-----------------------------
Nova Objectstore Server
-----------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-objectstore [options]

DESCRIPTION
===========

Implementation of an S3-like storage server based on local files.

Useful to test features that will eventually run on S3, or if you want to
run something locally that was once running on S3.

We don't support all the features of S3, but it does work with the
standard S3 client for the most basic semantics.

Used for testing when do not have OpenStack Swift installed.

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

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__
