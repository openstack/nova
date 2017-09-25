PowerVM
=======

Usage
-----
To make use of the PowerVM compute driver, a PowerVM system set up with
`NovaLink`_ is required.

.. _NovaLink: https://www.ibm.com/support/knowledgecenter/en/POWER8/p8eig/p8eig_kickoff.htm

Installing the NovaLink software creates the ``pvm_admin`` group. In
order to function properly, the user executing the Nova compute service must
be a member of this group. Use the ``usermod`` command to add the user. For
example, to add the user ``stacker`` to the ``pvm_admin`` group, execute::

  sudo usermod -a -G pvm_admin stacker

The user must re-login for the change to take effect.

The NovaLink architecture is such that the compute driver runs directly on the
PowerVM system. No external management element (e.g. Hardware Management
Console or PowerVC) is needed. Management of the virtualization is driven
through a thin virtual machine running on the PowerVM system.

Configuration of the PowerVM system and NovaLink is required ahead of time. If
the operator is using volumes or Shared Storage Pools, they are required to be
configured ahead of time.


Configuration File Options
--------------------------
After nova has been installed the user must enable PowerVM as the compute
driver. To do so, set the ``compute_driver`` value in the ``nova.conf`` file
to ``compute_driver = powervm.driver.PowerVMDriver``.
