=============
nova-rootwrap
=============

.. program:: nova-rootwrap

Synopsis
========

::

  nova-rootwrap [<options>...]

Description
===========

:program:`nova-rootwrap` is an application that filters which commands nova is
allowed to run as another user.

To use this, you should set the following in ``nova.conf``::

  rootwrap_config=/etc/nova/rootwrap.conf

You also need to let the nova user run :program:`nova-rootwrap` as root in
``sudoers``::

  nova ALL = (root) NOPASSWD: /usr/bin/nova-rootwrap /etc/nova/rootwrap.conf *

To make allowed commands node-specific, your packaging should only install
``{compute,network}.filters`` respectively on compute and network nodes, i.e.
:program:`nova-api` nodes should not have any of those files installed.

.. note::

   :program:`nova-rootwrap` is being slowly deprecated and replaced by
   ``oslo.privsep``, and will eventually be removed.

Options
=======

**General options**

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/rootwrap.conf``
* ``/etc/nova/rootwrap.d/``

See Also
========

* :nova-doc:`OpenStack Nova <>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
