=========
Real Time
=========

.. versionadded:: 13.0.0 (Mitaka)

Nova supports configuring `real-time policies`__ for instances. This builds upon
the improved performance offered by :doc:`CPU pinning <cpu-topologies>` by
providing stronger guarantees for worst case scheduler latency for vCPUs.

.. __: https://en.wikipedia.org/wiki/Real-time_computing


Enabling Real-Time
------------------

Currently the creation of real-time instances is only supported when using the
libvirt compute driver with a :oslo.config:option:`libvirt.virt_type` of
``kvm`` or ``qemu``. It requires extensive configuration of the host and this
document provides but a rough overview of the changes required. Configuration
will vary depending on your hardware, BIOS configuration, host and guest OS'
and application.

BIOS configuration
~~~~~~~~~~~~~~~~~~

Configure your host BIOS as recommended in the `rt-wiki`__ page.
The most important steps are:

- Disable power management, including CPU sleep states
- Disable SMT (hyper-threading) or any option related to logical processors

These are standard steps used in benchmarking as both sets of features can
result in non-deterministic behavior.

.. __: https://rt.wiki.kernel.org/index.php/HOWTO:_Build_an_RT-application

OS configuration
~~~~~~~~~~~~~~~~

This is inherently specific to the distro used, however, there are some common
steps:

- Install the real-time (preemptible) kernel (``PREEMPT_RT_FULL``) and
  real-time KVM modules
- Configure hugepages
- Isolate host cores to be used for instances from the kernel
- Disable features like CPU frequency scaling (e.g. P-States on Intel
  processors)

RHEL and RHEL-derived distros like CentOS provide packages in their
repositories to accomplish. The ``kernel-rt`` and ``kernel-rt-kvm``
packages will provide the real-time kernel and real-time KVM module,
respectively, while the ``tuned-profiles-realtime`` package will provide
`tuned`__ profiles to configure the host for real-time workloads. You should
refer to your distro documentation for more information.

.. __: https://tuned-project.org/

Validation
~~~~~~~~~~

Once your BIOS and the host OS have been configured, you can validate
"real-time readiness" using the ``hwlatdetect`` and ``rteval`` utilities. On
RHEL and RHEL-derived hosts, you can install these using the ``rt-tests``
package. More information about the ``rteval`` tool can be found `here`__.

.. __: https://git.kernel.org/pub/scm/utils/rteval/rteval.git/tree/README


Configuring a flavor or image
-----------------------------

.. versionchanged:: 22.0.0 (Victoria)

    Previously, it was necessary to specify
    :nova:extra-spec:`hw:cpu_realtime_mask` when realtime mode was enabled via
    :nova:extra-spec:`hw:cpu_realtime`. Starting in Victoria, it is possible
    to omit this when an emulator thread policy is configured using the
    :nova:extra-spec:`hw:emulator_threads_policy` extra spec, thus allowing all
    guest cores to be be allocated as real-time cores.

.. versionchanged:: 22.0.0 (Victoria)

    Previously, a leading caret was necessary when specifying the value for
    :nova:extra-spec:`hw:cpu_realtime_mask` and omitting it would be equivalent
    to not setting the mask, resulting in a failure to spawn the instance.

Compared to configuring the host, configuring the guest is relatively trivial
and merely requires a combination of flavor extra specs and image metadata
properties, along with a suitable real-time guest OS.

Enable real-time by setting the :nova:extra-spec:`hw:cpu_realtime` flavor extra
spec to ``yes`` or a truthy value. When this is configured, it is necessary to
specify where guest overhead processes should be scheduled to. This can be
accomplished in one of three ways. Firstly, the
:nova:extra-spec:`hw:cpu_realtime_mask` extra spec or equivalent image metadata
property can be used to indicate which guest cores should be scheduled as
real-time cores, leaving the remainder to be scheduled as non-real-time cores
and to handle overhead processes. For example, to allocate the first two cores
of an 8 core instance as the non-real-time cores:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property hw:cpu_realtime=yes \
       --property hw:cpu_realtime_mask=2-7  # so 0,1 are non-real-time

In this configuration, any non-real-time cores configured will have an implicit
``dedicated`` :ref:`CPU pinning policy <cpu-pinning-policies>` applied. It is
possible to apply a ``shared`` policy for these non-real-time cores by
specifying the ``mixed`` :ref:`CPU pinning policy <cpu-pinning-policies>` via
the :nova:extra-spec:`hw:cpu_policy` extra spec. This can be useful to increase
resource utilization of the host. For example:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property hw:cpu_policy=mixed \
       --property hw:cpu_realtime=yes \
       --property hw:cpu_realtime_mask=2-7  # so 0,1 are non-real-time and unpinned

Finally, you can explicitly :ref:`offload guest overhead processes to another
host core <emulator-thread-pinning-policies>` using the
:nova:extra-spec:`hw:emulator_threads_policy` extra spec. For example:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property hw:cpu_realtime=yes \
       --property hw:emulator_thread_policy=share

.. note::

    Emulator thread pinning requires additional host configuration.
    Refer to :ref:`the documentation <emulator-thread-pinning-policies>` for
    more information.

In addition to configuring the instance CPUs, it is also likely that you will
need to configure guest huge pages. For information on how to configure these,
refer to :doc:`the documentation <huge-pages>`

References
----------

* `Libvirt real time instances (spec)`__
* `The Real Time Linux collaborative project`__
* `Deploying Real Time OpenStack`__

.. __: https://specs.openstack.org/openstack/nova-specs/specs/mitaka/implemented/libvirt-real-time.html
.. __: https://wiki.linuxfoundation.org/realtime/start
.. __: https://that.guru/blog/deploying-real-time-openstack/
