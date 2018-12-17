================
nova-consoleauth
================

----------------------------------
Nova Console Authentication Server
----------------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-consoleauth [options]

Description
===========

:program:`nova-consoleauth` is a server daemon that serves the Nova Console
Auth service, which provides authentication for Nova consoles.

.. deprecated:: 18.0.0

   `nova-consoleauth` is deprecated since 18.0.0 (Rocky) and will be removed in
   an upcoming release. See
   :oslo.config:option:`workarounds.enable_consoleauth` for details.

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
