=============================================
Consider NUMA topology when booting instances
=============================================

.. todo:: Merge this into 'cpu-topologies.rst'

NUMA topology can exist on both the physical hardware of the host, and the
virtual hardware of the instance. OpenStack Compute uses libvirt to tune
instances to take advantage of NUMA topologies. The libvirt driver boot
process looks at the NUMA topology field of both the instance and the host it
is being booted on, and uses that information to generate an appropriate
configuration.

If the host is NUMA capable, but the instance has not requested a NUMA
topology, Compute attempts to pack the instance into a single cell.
If this fails, though, Compute will not continue to try.

If the host is NUMA capable, and the instance has requested a specific NUMA
topology, Compute will try to pin the vCPUs of different NUMA cells
on the instance to the corresponding NUMA cells on the host. It will also
expose the NUMA topology of the instance to the guest OS.

If you want Compute to pin a particular vCPU as part of this process,
set the ``vcpu_pin_set`` parameter in the ``nova.conf`` configuration
file. For more information about the ``vcpu_pin_set`` parameter, see the
Configuration Reference Guide.
