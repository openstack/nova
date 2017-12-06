PowerVM
=======

Introduction
------------
OpenStack Compute supports the PowerVM hypervisor through `NovaLink`_. In the
NovaLink architecture, a thin NovaLink virtual machine running on the Power
system manages virtualization for that system. The ``nova-compute`` service
can be installed on the NovaLink virtual machine and configured to use the
PowerVM compute driver. No external management element (e.g. Hardware
Management Console) is needed.

.. _NovaLink: https://www.ibm.com/support/knowledgecenter/en/POWER8/p8eig/p8eig_kickoff.htm

Configuration
-------------
In order to function properly, the ``nova-compute`` service must be executed
by a member of the ``pvm_admin`` group. Use the ``usermod`` command to add the
user. For example, to add the ``stacker`` user to the ``pvm_admin`` group, execute::

  sudo usermod -a -G pvm_admin stacker

The user must re-login for the change to take effect.

To enable the PowerVM compute driver, set the following configuration option
in the ``/etc/nova/nova.conf`` file:

.. code-block:: ini

   [Default]
   compute_driver = powervm.PowerVMDriver

The PowerVM driver supports two types of storage for ephemeral disks:
``localdisk`` or ``ssp``. If ``localdisk`` is selected, you must specify which
volume group should be used.  E.g.:

.. code-block:: ini

   [powervm]
   disk_driver = localdisk
   volume_group_name = openstackvg

.. note::

   Using the ``rootvg`` volume group is strongly discouraged since ``rootvg``
   is used by the management partition and filling this will cause failures.

The PowerVM driver also supports configuring the default amount of physical
processor compute power (known as "proc units") which will be given to each
vCPU. This value will be used if the requested flavor does not specify the
``powervm:proc_units`` extra-spec. A factor value of 1.0 means a whole physical
processor, whereas 0.05 means 1/20th of a physical processor. E.g.:

.. code-block:: ini

   [powervm]
   proc_units_factor = 0.1


Volume Support
--------------
Volume support is provided for the PowerVM virt driver via Cinder. Currently,
the only supported volume protocol is `vSCSI`_ Fibre Channel. Attach, detach,
and extend are the operations supported by the PowerVM vSCSI FC volume adapter.
Boot from volume is not yet supported.

.. _vSCSI: https://www.ibm.com/support/knowledgecenter/en/POWER8/p8hat/p8hat_virtualscsi.htm
