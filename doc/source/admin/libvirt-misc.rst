======================
Other libvirt features
======================

The libvirt driver supports a large number of additional features that don't
warrant their own section. These are gathered here.


Guest agent support
-------------------

Guest agents enable optional access between compute nodes and guests through a
socket, using the QMP protocol.

To enable this feature, you must set ``hw_qemu_guest_agent=yes`` as a metadata
parameter on the image you wish to use to create the guest-agent-capable
instances from. You can explicitly disable the feature by setting
``hw_qemu_guest_agent=no`` in the image metadata.


.. _extra-specs-watchdog-behavior:

Watchdog behavior
-----------------

.. versionchanged:: 15.0.0 (Ocata)

   Add support for the ``disabled`` option.

A virtual watchdog device can be used to keep an eye on the guest server and
carry out a configured action if the server hangs. The watchdog uses the
i6300esb device (emulating a PCI Intel 6300ESB). Watchdog behavior can be
configured using the :nova:extra-spec:`hw:watchdog_action` flavor extra spec or
equivalent image metadata property. If neither the extra spec not the image
metadata property are specified, the watchdog is disabled.

For example, to enable the watchdog and configure it to forcefully reset the
guest in the event of a hang, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw:watchdog_action=reset

.. note::

   Watchdog behavior set using the image metadata property will override
   behavior set using the flavor extra spec.


.. _extra-specs-random-number-generator:

Random number generator
-----------------------

.. versionchanged:: 21.0.0 (Ussuri)

    Random number generators are now enabled by default for instances.

Operating systems require good sources of entropy for things like cryptographic
software. If a random-number generator device has been added to the instance
through its image properties, the device can be enabled and configured using
the :nova:extra-spec:`hw_rng:allowed`, :nova:extra-spec:`hw_rng:rate_bytes` and
:nova:extra-spec:`hw_rng:rate_period` flavor extra specs.

To configure for example a byte rate of 5 bytes per period and a period of 1000
mSec (1 second), run:

.. code-block:: console

   $ openstack flavor set $FLAVOR \
       --property hw_rng:rate_bytes=5 \
       --property hw_rng:rate_period=1000

Alternatively, to disable the random number generator, run:

.. code-block:: console

   $ openstack flavor set $FLAVOR --property hw_rng:allowed=false

The presence of separate byte rate and rate period configurables is
intentional. As noted in the `QEMU docs`__, a smaller rate and larger period
minimizes the opportunity for malicious guests to starve other guests of
entropy but at the cost of responsiveness. Conversely, larger rates and smaller
periods will increase the burst rate but at the potential cost of warping
resource consumption in favour of a greedy guest.

.. __: https://wiki.qemu.org/Features/VirtIORNG#Effect_of_the_period_parameter


.. _extra-specs-performance-monitoring-unit:

Performance Monitoring Unit (vPMU)
----------------------------------

.. versionadded:: 20.0.0 (Train)

If nova is deployed with the libvirt virt driver and
:oslo.config:option:`libvirt.virt_type` is set to ``qemu`` or ``kvm``, a
virtual performance monitoring unit (vPMU) can be enabled or disabled for an
instance using the :nova:extra-spec:`hw:pmu` flavor extra spec or ``hw_pmu``
image metadata property.
If the vPMU is not explicitly enabled or disabled via
the flavor or image, its presence is left to QEMU to decide.

For example, to explicitly disable the vPMU, run:

.. code-block:: console

   $ openstack flavor set FLAVOR-NAME --property hw:pmu=false

The vPMU is used by tools like ``perf`` in the guest to provide more accurate
information for profiling application and monitoring guest performance.
For :doc:`real time </admin/real-time>` workloads, the emulation of a vPMU can
introduce additional latency which would be undesirable. If the telemetry it
provides is not required, the vPMU can be disabled. For most workloads the
default of unset (enabled) will be correct.


.. _extra-specs-hiding-hypervisor-signature:

Hiding hypervisor signature
---------------------------

.. versionadded:: 18.0.0 (Rocky)

.. versionchanged:: 21.0.0 (Ussuri)

   Prior to the Ussuri release, this was called ``hide_hypervisor_id``. An
   alias is provided to provide backwards compatibility.

Some hypervisors add a signature to their guests. While the presence of the
signature can enable some paravirtualization features on the guest, it can also
have the effect of preventing some drivers from loading. You can hide this
signature by setting the :nova:extra-spec:`hw:hide_hypervisor_id` to true.

For example, to hide your signature from the guest OS, run:

.. code:: console

   $ openstack flavor set $FLAVOR --property hw:hide_hypervisor_id=true


.. _extra-spec-locked_memory:

Locked memory allocation
------------------------

.. versionadded:: 26.0.0 (Zed)

Locking memory marks the guest memory allocations as unmovable and
unswappable. It is implicitly enabled in a number of cases such as SEV or
realtime guests but can also be enabled explicitly using the
``hw:locked_memory`` extra spec (or use ``hw_locked_memory`` image property).
``hw:locked_memory`` (also ``hw_locked_memory`` image property) accept
boolean values in string format like 'true' or 'false' value.
It will raise `FlavorImageLockedMemoryConflict` exception if both flavor and
image property are specified but with different boolean values.
This will only be allowed if you have also set ``hw:mem_page_size``,
so we can ensure that the scheduler can actually account for this correctly
and prevent out of memory events. Otherwise, will raise `LockMemoryForbidden`
exception.

.. code:: console

   $ openstack flavor set FLAVOR-NAME \
       --property hw:locked_memory=BOOLEAN_VALUE

.. note::

   This is currently only supported by the libvirt driver.
