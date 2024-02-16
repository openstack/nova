==========
CPU models
==========

Nova allows you to configure features of the virtual CPU that are exposed to
instances. The combined set of CPU features is collectively referred to as the
*CPU model*. Use cases include:

* To maximize performance of instances by exposing new host CPU features to the
  guest

* To ensure a consistent default behavior across all machines, removing
  reliance on system defaults.

To configure the virtual CPU, you can configure a :ref:`CPU mode <cpu-modes>`,
configure one or more :ref:`named CPU models <cpu-models>`, and explicitly
request :ref:`cpu-feature-flags`.

The `Effective Virtual CPU configuration in Nova`__ presentation from the 2018
Berlin Summit provides a good overview of this topic.

.. note::

   It is also possible to configure the topology of the CPU. This is discussed
   in :doc:`cpu-topologies`.

.. important::

   The functionality described below is currently only supported by the
   libvirt driver.

.. __: https://www.openstack.org/videos/summits/berlin-2018/effective-virtual-cpu-configuration-in-nova


.. _cpu-modes:

CPU modes
---------

The first step in configuring the guest CPU is configuring the CPU *mode*.
The CPU mode determines whether the CPU model is configured manually based on
admin configuration or is automatically configured based on the host CPU.
The CPU mode is configured using the :oslo.config:option:`libvirt.cpu_mode`
config option. This option can accepts one of the following values: ``none``,
``host-passthrough``, ``host-model``, and ``custom``.

Host model
~~~~~~~~~~

If :oslo.config:option:`cpu_mode=host-model <libvirt.cpu_mode>`, libvirt
requests the :ref:`named CPU model <cpu-models>` that most closely matches the
host and requests additional CPU flags to complete the match. This CPU model
has a number of advantages:

* It provides almost all of the host CPU features to the guest, thus providing
  close to the maximum functionality and performance possible.

* It auto-adds critical guest CPU flags for mitigation from certain security
  flaws, *provided* the CPU microcode, kernel, QEMU, and libvirt are all
  updated.

* It computes live migration compatibility, with the caveat that live migration
  in both directions is not always possible.

In general, using ``host-model`` is a safe choice if your compute node CPUs are
largely identical. However, if your compute nodes span multiple processor
generations, you may be better advised to select a ``custom`` CPU model.

The ``host-model`` CPU mode is the effective default for the KVM & QEMU
hypervisors (:oslo.config:option:`libvirt.virt_type`\ =\ ``kvm``/``qemu``) on
x86-64 hosts. This default is provided by libvirt itself.

.. note::

   As noted above, live migration is not always possible in both directions
   when using ``host-model``. During live migration, the source CPU model
   definition is transferred to the destination host as-is. This results in the
   migrated guest on the destination seeing exactly the same CPU model as on
   source even if the destination compute host is capable of providing more CPU
   features. However, shutting down and restarting the guest may result in a
   different hardware configuration for the guest, as per the new capabilities
   of the destination compute.

Host passthrough
~~~~~~~~~~~~~~~~

If :oslo.config:option:`cpu_mode=host-passthrough <libvirt.cpu_mode>`, libvirt
tells KVM to pass through the host CPU with no modifications. In comparison to
``host-model`` which simply matches feature flags, ``host-passthrough`` ensures
every last detail of the host CPU is matched. This gives the best performance,
and can be important to some apps which check low level CPU details, but it
comes at a cost with respect to migration.

In ``host-passthrough`` mode, the guest can only be live-migrated to a target
host that matches the source host extremely closely. This includes the physical
CPU model and running microcode, and may even include the running kernel. Use
this mode only if your compute nodes have a very large degree of homogeneity
(i.e. substantially all of your compute nodes use the exact same CPU generation
and model), and you make sure to only live-migrate between hosts with exactly
matching kernel versions. Failure to do so will result in an inability to
support any form of live migration.

.. note::

   The reason for that it is necessary for the CPU microcode versions to match
   is that hardware performance counters are exposed to an instance and it is
   likely that they may vary between different CPU models. There may also be
   other reasons due to security fixes for some hardware security flaws being
   included in CPU microcode.

Custom
~~~~~~

If :oslo.config:option:`cpu_mode=custom <libvirt.cpu_mode>`, you can explicitly
specify an ordered list of one or more supported named CPU models using the
:oslo.config:option:`libvirt.cpu_models` configuration option. This accepts any
named CPU model that is valid for the given host, as discussed in
:ref:`cpu-models` below. When more than one CPU model is provided, it is
expected that the list will be ordered so that the more common and less
advanced CPU models are listed first.

In selecting the ``custom`` mode, along with a named CPU model that matches the
oldest of your compute node CPUs, you can ensure that live migration between
compute nodes will always be possible. However, you should ensure that the CPU
model you select passes the correct CPU feature flags to the guest.

If you need to further tweak your CPU feature flags in the ``custom`` mode, see
:ref:`cpu-feature-flags`.

.. note::

   If :oslo.config:option:`libvirt.cpu_models` is configured,
   the CPU models in the list needs to be compatible with the host CPU. Also, if
   :oslo.config:option:`libvirt.cpu_model_extra_flags` is configured, all flags
   needs to be compatible with the host CPU. If incompatible CPU models or flags
   are specified, nova service will raise an error and fail to start.

None
~~~~

If :oslo.config:option:`cpu_mode=none <libvirt.cpu_mode>`, libvirt does not
specify a CPU model. Instead, the hypervisor chooses the default model.

The ``none`` CPU model is the default for all non-KVM/QEMU hypervisors.
(:oslo.config:option:`libvirt.virt_type`\ !=``kvm``/``qemu``)


.. _cpu-models:

CPU models
----------

When :oslo.config:option:`libvirt.cpu_mode` is set to ``custom``, it is
possible to configure one or more explicit CPU models that should be used.
These CPU model names are shorthand for a set of feature flags.
The libvirt KVM driver provides a number of standard CPU model names.
These models are defined in ``/usr/share/libvirt/cpu_map/*.xml``.
You can inspect these files to determine which models are supported by your
local installation. For example, consider a host that provides the following
(incomplete) set of CPU models:

.. code-block:: bash

    $ ls /usr/share/libvirt/cpu_map/x86_*.xml -1
    ...
    /usr/share/libvirt/cpu_map/x86_Broadwell-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Broadwell-noTSX-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Broadwell-noTSX.xml
    /usr/share/libvirt/cpu_map/x86_Broadwell.xml
    /usr/share/libvirt/cpu_map/x86_Haswell-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Haswell-noTSX-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Haswell-noTSX.xml
    /usr/share/libvirt/cpu_map/x86_Haswell.xml
    /usr/share/libvirt/cpu_map/x86_Icelake-Client-noTSX.xml
    /usr/share/libvirt/cpu_map/x86_Icelake-Client.xml
    /usr/share/libvirt/cpu_map/x86_Icelake-Server-noTSX.xml
    /usr/share/libvirt/cpu_map/x86_Icelake-Server.xml
    /usr/share/libvirt/cpu_map/x86_IvyBridge-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_IvyBridge.xml
    /usr/share/libvirt/cpu_map/x86_SandyBridge-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_SandyBridge.xml
    /usr/share/libvirt/cpu_map/x86_Skylake-Client-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Skylake-Client-noTSX-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Skylake-Client.xml
    /usr/share/libvirt/cpu_map/x86_Skylake-Server-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Skylake-Server-noTSX-IBRS.xml
    /usr/share/libvirt/cpu_map/x86_Skylake-Server.xml
    ...

Each of these files contains information about the feature set provided by the
CPU model. For example:

.. code-block:: bash

    $ cat /usr/share/libvirt/cpu_map/x86_SandyBridge-IBRS.xml
    <cpus>
      <model name='SandyBridge-IBRS'>
        <decode host='on' guest='on'/>
        <signature family='6' model='42'/> <!-- 0206a0 -->
        <signature family='6' model='45'/> <!-- 0206d0 -->
        <vendor name='Intel'/>
        <feature name='aes'/>
        <feature name='apic'/>
        ...
      </model>
    </cpus>

You can also list these CPU models using ``virsh cpu-models ARCH``.
For example:

.. code-block:: bash

    $ virsh cpu-models x86_64
    ...
    SandyBridge
    SandyBridge-IBRS
    IvyBridge
    IvyBridge-IBRS
    Haswell-noTSX
    Haswell-noTSX-IBRS
    Haswell
    Haswell-IBRS
    Broadwell-noTSX
    Broadwell-noTSX-IBRS
    Broadwell
    Broadwell-IBRS
    Skylake-Client
    Skylake-Client-IBRS
    Skylake-Client-noTSX-IBRS
    Skylake-Server
    Skylake-Server-IBRS
    Skylake-Server-noTSX-IBRS
    Icelake-Client
    Icelake-Client-noTSX
    Icelake-Server
    Icelake-Server-noTSX
    ...

By settings :oslo.config:option:`cpu_mode=custom <libvirt.cpu_mode>`, it is
possible to list one or more of these CPU models in the
:oslo.config:option:`libvirt.cpu_models` config option in ``nova.conf``. For
example:

.. code-block:: ini

    [libvirt]
    cpu_mode = custom
    cpu_models = IvyBridge

Typically you will only need to list a single model here, but it can be useful
to list multiple CPU models to support requesting CPU feature flags via traits.
To do this, simply list the additional CPU models in order of oldest (and
therefore most widely supported) to newest. For example:

.. code-block:: ini

    [libvirt]
    cpu_mode = custom
    cpu_models = Penryn,IvyBridge,Haswell,Broadwell,Skylake-Client

More details on how to request CPU feature flags and why you might wish to
specify multiple CPU models are provided in :ref:`cpu-feature-flags` below.


.. _cpu-feature-flags:

CPU feature flags
-----------------

.. versionadded:: 18.0.0 (Rocky)

Regardless of your configured :oslo.config:option:`libvirt.cpu_mode`, it is
also possible to selectively enable additional feature flags. This can be
accomplished using the :oslo.config:option:`libvirt.cpu_model_extra_flags`
config option. For example, suppose you have configured a custom CPU model of
``IvyBridge``, which normally does not enable the ``pcid`` feature flag, but
you do want to pass ``pcid`` into your guest instances. In this case, you could
configure the following in ``nova.conf`` to enable this flag.

.. code-block:: ini

   [libvirt]
   cpu_mode = custom
   cpu_models = IvyBridge
   cpu_model_extra_flags = pcid

An end user can also specify required CPU features through traits. When
specified, the libvirt driver will select the first CPU model in the
:oslo.config:option:`libvirt.cpu_models` list that can provide the requested
feature traits. If no CPU feature traits are specified then the instance will
be configured with the first CPU model in the list.

Consider the following ``nova.conf``:

.. code-block:: ini

    [libvirt]
    cpu_mode = custom
    cpu_models = Penryn,IvyBridge,Haswell,Broadwell,Skylake-Client

These different CPU models support different feature flags and are correctly
configured in order of oldest (and therefore most widely supported) to newest.
If the user explicitly required the ``avx`` and ``avx2`` CPU features, the
latter of which is only found of Haswell-generation processors or newer, then
they could request them using the
:nova:extra-spec:`trait{group}:HW_CPU_X86_AVX` and
:nova:extra-spec:`trait{group}:HW_CPU_X86_AVX2` flavor extra specs. For
example:

.. code-block:: console

    $ openstack flavor set $FLAVOR \
        --property trait:HW_CPU_X86_AVX=required \
        --property trait:HW_CPU_X86_AVX2=required

As ``Haswell`` is the first CPU model supporting both of these CPU features,
the instance would be configured with this model.

.. _mitigation-for-Intel-MDS-security-flaws:

Mitigation for MDS ("Microarchitectural Data Sampling") Security Flaws
----------------------------------------------------------------------

In May 2019, four new microprocessor flaws, known as `MDS`__ and also referred
to as `RIDL and Fallout`__ or `ZombieLoad`__, were discovered.
These flaws affect unpatched Nova compute nodes and instances running on Intel
x86_64 CPUs.

.. __: https://access.redhat.com/security/vulnerabilities/mds
.. __: https://mdsattacks.com/
.. __: https://zombieloadattack.com

Resolution
~~~~~~~~~~

To get mitigation for the said MDS security flaws, a new CPU flag,
``md-clear``, needs to be exposed to the Nova instances. This can be done as
follows.

#. Update the following components to the versions from your Linux
   distribution that have fixes for the MDS flaws, on all compute nodes
   with Intel x86_64 CPUs:

   - ``microcode_ctl``
   - ``kernel``
   - ``qemu-system-x86``
   - ``libvirt``

#. When using the libvirt driver, ensure that the CPU flag ``md-clear``
   is exposed to the Nova instances.  This can be done in one of three ways,
   depending on your configured CPU mode:

   #. :oslo.config:option:`libvirt.cpu_mode`\ =host-model

      When using the ``host-model`` CPU mode, the ``md-clear`` CPU flag
      will be passed through to the Nova guests automatically.

      This mode is the default, when
      :oslo.config:option:`libvirt.virt_type`\ =kvm|qemu is set in
      ``/etc/nova/nova-cpu.conf`` on compute nodes.

   #. :oslo.config:option:`libvirt.cpu_mode`\ =host-passthrough

      When using the ``host-passthrough`` CPU mode, the ``md-clear`` CPU
      flag will be passed through to the Nova guests automatically.

   #. :oslo.config:option:`libvirt.cpu_mode`\ =custom

      When using the ``custom`` CPU mode, you must *explicitly* enable the
      CPU flag ``md-clear`` to the Nova instances, in addition to the
      flags required for previous vulnerabilities, using the
      :oslo.config:option:`libvirt.cpu_model_extra_flags`.  For example:

      .. code-block:: ini

           [libvirt]
           cpu_mode = custom
           cpu_models = IvyBridge
           cpu_model_extra_flags = spec-ctrl,ssbd,md-clear

#. Reboot the compute node for the fixes to take effect.

   To minimize workload downtime, you may wish to live migrate all guests to
   another compute node first.

Once the above steps have been taken on every vulnerable compute node in the
deployment, each running guest in the cluster must be fully powered down, and
cold-booted (i.e. an explicit stop followed by a start), in order to activate
the new CPU models. This can be done by the guest administrators at a time of
their choosing.

Validation
~~~~~~~~~~

After applying relevant updates, administrators can check the kernel's
``sysfs`` interface to see what mitigation is in place, by running the
following command on the host:

.. code-block:: bash

   # cat /sys/devices/system/cpu/vulnerabilities/mds
   Mitigation: Clear CPU buffers; SMT vulnerable

To unpack the message "Mitigation: Clear CPU buffers; SMT vulnerable":

- ``Mitigation: Clear CPU buffers`` means you have the "CPU buffer clearing"
  mitigation enabled, which is mechanism to invoke a flush of various
  exploitable CPU buffers by invoking a CPU instruction called "VERW".

- ``SMT vulnerable`` means, depending on your workload, you may still be
  vulnerable to SMT-related problems. You need to evaluate whether your
  workloads need SMT (also called "Hyper-Threading") to be disabled or not.
  Refer to the guidance from your Linux distribution and processor vendor.

To see the other possible values for
``/sys/devices/system/cpu/vulnerabilities/mds``, refer to the `MDS system
information`__ section in Linux kernel's documentation for MDS.

On the host, validate that KVM is capable of exposing the ``md-clear`` flag to
guests:

.. code-block:: bash

   # virsh domcapabilities kvm | grep md-clear
   <feature policy='require' name='md-clear'/>

More information can be found on the 'Diagnosis' tab of `this security notice
document`__.

.. __: https://www.kernel.org/doc/html/latest/admin-guide/hw-vuln/mds.html#mds-system-information
.. __: https://access.redhat.com/security/vulnerabilities/mds

Performance Impact
~~~~~~~~~~~~~~~~~~

Refer to this section titled "Performance Impact and Disabling MDS" from
`this security notice document`__, under the *Resolve* tab.

.. note::

   Although the article referred to is from Red Hat, the findings and
   recommendations about performance impact apply for other distributions also.

.. __: https://access.redhat.com/security/vulnerabilities/mds
