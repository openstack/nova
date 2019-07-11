======================================================================
Mitigation for MDS ("Microarchitectural Data Sampling") Security Flaws
======================================================================

Issue
~~~~~

In May 2019, four new microprocessor flaws, known as `MDS
<https://access.redhat.com/security/vulnerabilities/mds>`_ , have been
discovered.  These flaws affect unpatched Nova compute nodes and
instances running on Intel x86_64 CPUs.  (The said MDS security flaws
are also referred to as `RIDL and Fallout <https://mdsattacks.com/>`_ or
`ZombieLoad <https://zombieloadattack.com>`_).


Resolution
~~~~~~~~~~

To get mitigation for the said MDS security flaws, a new CPU flag,
`md-clear`, needs to be exposed to the Nova instances.  It can be done
as follows.

(1) Update the following components to the versions from your Linux
    distribution that have fixes for the MDS flaws, on all compute nodes
    with Intel x86_64 CPUs:

    - microcode_ctl
    - kernel
    - qemu-system-x86
    - libvirt

(2) When using the libvirt driver, ensure that the CPU flag ``md-clear``
    is exposed to the Nova instances.  It can be done so in one of the
    three following ways, given that Nova supports three distinct CPU
    modes:

    a. :oslo.config:option:`libvirt.cpu_mode`\ =host-model

       When using ``host-model`` CPU mode, the ``md-clear`` CPU flag
       will be passed through to the Nova guests automatically.

       This mode is the default, when
       :oslo.config:option:`libvirt.virt_type`\ =kvm|qemu is set in
       ``/etc/nova/nova-cpu.conf`` on compute nodes.

    b. :oslo.config:option:`libvirt.cpu_mode`\ =host-passthrough

       When using ``host-passthrough`` CPU mode, the ``md-clear`` CPU
       flag will be passed through to the Nova guests automatically.

    c. Specific custom CPU models — this can be enabled using the
       Nova config attributes :oslo.config:option:`libvirt.cpu_mode`\ =custom
       plus particular named CPU models, e.g.
       :oslo.config:option:`libvirt.cpu_models`\ =IvyBridge.

       (The list of all valid named CPU models that are supported by
       your host, QEMU, and libvirt can be found by running the
       command ``virsh domcapabilities``.)

       When using a custom CPU mode, you must *explicitly* enable the
       CPU flag ``md-clear`` to the Nova instances, in addition to the
       flags required for previous vulnerabilities, using the
       :oslo.config:option:`libvirt.cpu_model_extra_flags`.  E.g.::

           [libvirt]
           cpu_mode = custom
           cpu_models = IvyBridge
           cpu_model_extra_flags = spec-ctrl,ssbd,md-clear

(3) Reboot the compute node for the fixes to take effect.  (To minimize
    workload downtime, you may wish to live migrate all guests to
    another compute node first.)

Once the above steps have been taken on every vulnerable compute
node in the deployment, each running guest in the cluster must be
fully powered down, and cold-booted (i.e. an explicit stop followed
by a start), in order to activate the new CPU models.  This can be done
by the guest administrators at a time of their choosing.


Validate that the fixes are in effect
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After applying relevant updates, administrators can check the kernel's
"sysfs" interface to see what mitigation is in place, by running the
following command (on the host)::

    # cat /sys/devices/system/cpu/vulnerabilities/mds
    Mitigation: Clear CPU buffers; SMT vulnerable

To unpack the message "Mitigation: Clear CPU buffers; SMT vulnerable":

  - The ``Mitigation: Clear CPU buffers`` bit means, you have the "CPU
    buffer clearing" mitigation enabled (which is mechanism to invoke a
    flush of various exploitable CPU buffers by invoking a CPU
    instruction called "VERW").

  - The ``SMT vulnerable`` bit means, depending on your workload, you may
    still be vulnerable to SMT-related problems.  You need to evaluate
    whether your workloads need SMT (also called "Hyper-Threading") to
    be disabled or not.  Refer to the guidance from your Linux
    distribution and processor vendor.

To see the other possible values for the sysfs file,
``/sys/devices/system/cpu/vulnerabilities/mds``, refer to the `MDS
system information
<https://www.kernel.org/doc/html/latest/admin-guide/hw-vuln/mds.html#mds-system-information>`_
section in Linux kernel's documentation for MDS.

On the host, validate that KVM is capable of exposing the ``md-clear``
flag to guests::

    # virsh domcapabilities kvm | grep md-clear
        <feature policy='require' name='md-clear'/>

Also, refer to the 'Diagnosis' tab in this security notice document
`here <https://access.redhat.com/security/vulnerabilities/mds>`_


Performance Impact
~~~~~~~~~~~~~~~~~~

Refer to this section titled "Performance Impact and Disabling MDS" from
the security notice document `here
<https://access.redhat.com/security/vulnerabilities/mds>`_, under the
'Resolve' tab.  (Note that although the article referred to is from Red
Hat, the findings and recommendations about performance impact apply
for other distributions as well.)
