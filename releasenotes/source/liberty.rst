==============================
 Liberty Series Release Notes
==============================

.. _Release Notes_12.0.5_stable_liberty:

12.0.5
======

.. _Release Notes_12.0.5_stable_liberty_Security Issues:

Security Issues
---------------

.. releasenotes/notes/apply-limits-to-qemu-img-8813f7a333ebdf69.yaml @ b'6bc37dcceca823998068167b49aec6def3112397'

- The qemu-img tool now has resource limits applied which prevent it from using more than 1GB of address space or more than 2 seconds of CPU time. This provides protection against denial of service attacks from maliciously crafted or corrupted disk images. oslo.concurrency>=2.6.1 is required for this fix.


.. _Release Notes_12.0.4_stable_liberty:

12.0.4
======

.. _Release Notes_12.0.4_stable_liberty_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1559026-47c3fa3468d66b07.yaml @ b'79a49b3d6a4221ca3e09cb16008cc423f1902fe7'

- The ``record`` configuration option for the console proxy services (like VNC, serial, spice) is changed from boolean to string. It specifies the filename that will be used for recording websocket frames.


.. _Release Notes_12.0.4_stable_liberty_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/vhost-user-mtu-23d0af36a8adfa56.yaml @ b'98464d54d0fcdba452191bc0291d59957c9cdae6'

- When plugging virtual interfaces of type vhost-user the MTU value will not be applied to the interface by nova. vhost-user ports exist only in userspace and are not backed by kernel netdevs, for this reason it is not possible to set the mtu on a vhost-user interface using standard tools such as ifconfig or ip link.


.. _Release Notes_12.0.3_stable_liberty:

12.0.3
======

.. _Release Notes_12.0.3_stable_liberty_Security Issues:

Security Issues
---------------

.. releasenotes/notes/12.0.3-cve-bugs-reno-561a450b346edf5e.yaml @ b'0b194187db9da28225cb5e62be3b45aff5a1c793'

- [OSSA 2016-007] Host data leak during resize/migrate for raw-backed instances  (CVE-2016-2140)

  * `Bug 1548450 <https://bugs.launchpad.net/nova/+bug/1548450>`_
  * `Announcement <http://lists.openstack.org/pipermail/openstack-announce/2016-March/001009.html>`__


.. _Release Notes_12.0.1_stable_liberty:

12.0.1
======

.. _Release Notes_12.0.1_stable_liberty_Prelude:

Prelude
-------

.. releasenotes/notes/12.0.1-cve-bugs-7b04b2e34a3e9a70.yaml @ b'9c3cce75de6069edca35ce5046d4ce25a11b6337'

The 12.0.1 release contains fixes for two security issues.


.. _Release Notes_12.0.1_stable_liberty_Security Issues:

Security Issues
---------------

.. releasenotes/notes/12.0.1-cve-bugs-7b04b2e34a3e9a70.yaml @ b'9c3cce75de6069edca35ce5046d4ce25a11b6337'

- [OSSA 2016-001] Nova host data leak through snapshot (CVE-2015-7548)

  * `Bug 1524274 <https://bugs.launchpad.net/nova/+bug/1524274>`_
  * `Announcement <http://lists.openstack.org/pipermail/openstack-announce/2016-January/000911.html>`__

  [OSSA 2016-002] Xen connection password leak in logs via StorageError (CVE-2015-8749)

  * `Bug 1516765 <https://bugs.launchpad.net/nova/+bug/1516765>`_
  * `Announcement <http://lists.openstack.org/pipermail/openstack-announce/2016-January/000916.html>`__


.. _Release Notes_12.0.1_stable_liberty_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1505471-28ef47bdc9487a31.yaml @ b'821f644e98475d0af53f621ba13930b3dffc6e7b'

- Fixes a bug where Nova services won't recover after a temporary DB
  connection issue, when service group DB driver is used together with
  local conductor, as the driver only handles RPC timeout errors.

  For more info see https://bugs.launchpad.net/nova/+bug/1505471

.. releasenotes/notes/bug-1517926-ed0dda23ea525306.yaml @ b'821f644e98475d0af53f621ba13930b3dffc6e7b'

- Fixes a bug where Nova services won't recover after a temporary DB / MQ
  connection issue, when service group DB driver is used together with
  remote conductor, as the driver only handles RPC timeout errors and does
  not account for other types of errors (e.g. wrapped DB errors on the
  remote conductor transported over RPC)

  For more info see https://bugs.launchpad.net/nova/+bug/1517926


.. _Release Notes_12.0.1_stable_liberty_Other Notes:

Other Notes
-----------

.. releasenotes/notes/start-using-reno-e4ea112d593415da.yaml @ b'70fbad45d9d8459b141b81820ea12b27900a3bab'

- Start using reno to manage release notes.


