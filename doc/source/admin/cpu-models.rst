==========
CPU models
==========

Nova allows you to control the guest CPU model that is exposed to instances.
Use cases include:

* To maximize performance of instances by exposing new host CPU features to the
  guest

* To ensure a consistent default behavior across all machines, removing
  reliance on system defaults.

.. important::

   The functionality described below is currently only supported by the
   libvirt driver.


CPU modes
---------

In libvirt, the CPU is specified by providing a base CPU model name (which is a
shorthand for a set of feature flags), a set of additional feature flags, and
the topology (sockets/cores/threads). The libvirt KVM driver provides a number
of standard CPU model names. These models are defined in
``/usr/share/libvirt/cpu_map/*.xml``. You can inspect these files to determine
which models are supported by your local installation.

Two Compute configuration options in the :oslo.config:group:`libvirt` group
of ``nova.conf`` define which type of CPU model is exposed to the hypervisor
when using KVM: :oslo.config:option:`libvirt.cpu_mode` and
:oslo.config:option:`libvirt.cpu_models`.

The :oslo.config:option:`libvirt.cpu_mode` option can take one of the following
values: ``none``, ``host-passthrough``, ``host-model``, and ``custom``.

See `Effective Virtual CPU configuration in Nova`__ for a recorded presentation
about this topic.

.. __: https://www.openstack.org/videos/summits/berlin-2018/effective-virtual-cpu-configuration-in-nova

Host model
~~~~~~~~~~

If :oslo.config:option:`cpu_mode=host-model <libvirt.cpu_mode>`, the CPU model
in ``/usr/share/libvirt/cpu_map/*.xml`` that most closely matches the host, and
requests additional CPU flags to complete the match. This configuration
provides the maximum functionality and performance and maintains good
reliability.

With regard to enabling and facilitating live migration between
compute nodes, you should assess whether ``host-model`` is suitable
for your compute architecture. In general, using ``host-model`` is a
safe choice if your compute node CPUs are largely identical. However,
if your compute nodes span multiple processor generations, you may be
better advised to select a ``custom`` CPU model.

The ``host-model`` CPU model is the default for the KVM & QEMU hypervisors
(:oslo.config:option:`libvirt.virt_type`\ =``kvm``/``qemu``)

Host passthrough
~~~~~~~~~~~~~~~~

If :oslo.config:option:`cpu_mode=host-passthrough <libvirt.cpu_mode>`, libvirt
tells KVM to pass through the host CPU with no modifications. In comparison to
``host-model`` which simply matches feature flags, ``host-passthrough`` ensures
every last detail of the host CPU is matched. This gives the best performance,
and can be important to some apps which check low level CPU details, but it
comes at a cost with respect to migration.

In ``host-passthrough`` mode, the guest can only be live-migrated to a
target host that matches the source host extremely closely. This
definitely includes the physical CPU model and running microcode, and
may even include the running kernel. Use this mode only if:

* Your compute nodes have a very large degree of homogeneity
  (i.e. substantially all of your compute nodes use the exact same CPU
  generation and model), and you make sure to only live-migrate
  between hosts with exactly matching kernel versions, *or*

* You decide, for some reason and against established best practices,
  that your compute infrastructure should not support any live
  migration at all.

Custom
~~~~~~

If :oslo.config:option:`cpu_mode=custom <libvirt.cpu_mode>`, you can explicitly
specify an ordered list of supported named models using the
:oslo.config:option:`libvirt.cpu_models` configuration option. It is expected
that the list is ordered so that the more common and less advanced CPU models
are listed earlier.

In selecting the ``custom`` mode, along with a
:oslo.config:option:`libvirt.cpu_models` that matches the oldest of your compute
node CPUs, you can ensure that live migration between compute nodes will always
be possible. However, you should ensure that the
:oslo.config:option:`libvirt.cpu_models` you select passes the correct CPU
feature flags to the guest.

If you need to further tweak your CPU feature flags in the ``custom`` mode, see
`CPU feature flags`_.

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

The ``none`` CPU model is the default for all non-KVM.QEMU hypervisors.
(:oslo.config:option:`libvirt.virt_type`\ !=``kvm``/``qemu``)


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
