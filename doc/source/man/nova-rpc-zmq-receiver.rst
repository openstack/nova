=======================
nova-rpc-zmq-receiver
=======================

-----------------------------------
Receiver for 0MQ based nova RPC
-----------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  nova-rpc-zmq-receiver [options]

DESCRIPTION
===========

The nova-rpc-zmq-receiver is a daemon which receives messages from remote
systems on behalf of the ZeroMQ-based rpc backend (nova.rpc.impl_zmq).
Messages are pulled by individual services from the message receiver daemon
in round-robin or fanout mode, depending on the queue type.

OPTIONS
=======

 **General options**

FILES
========

* /etc/nova/nova.conf

SEE ALSO
========

* `OpenStack Nova <http://nova.openstack.org>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__
