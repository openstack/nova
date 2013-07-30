==========
nova-cert
==========

--------------------------------
Server for the Nova Cert
--------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-cert [options]

DESCRIPTION
===========

nova-cert is a server daemon that serves the Nova Cert service for X509 certificates.  Used to generate certificates for euca-bundle-image.  Only needed for EC2 API.

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
