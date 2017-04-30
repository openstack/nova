========
nova-api
========

-------------------------------------------
Server for the Nova EC2 and OpenStack APIs
-------------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-api  [options]

DESCRIPTION
===========

nova-api is a server daemon that serves the metadata and compute APIs in
separate greenthreads

OPTIONS
=======

 **General options**

FILES
========

* /etc/nova/nova.conf
* /etc/nova/api-paste.ini
* /etc/nova/policy.json
* /etc/nova/rootwrap.conf
* /etc/nova/rootwrap.d/

SEE ALSO
========

* `OpenStack Nova <https://docs.openstack.org/developer/nova>`__
* `Using WSGI with Nova <https://docs.openstack.org/devloper/nova/wsgi.html>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__
