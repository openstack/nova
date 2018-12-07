..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

====================================
 ComputeDriver.update_provider_tree
====================================

This provides details on the ``ComputeDriver`` abstract method
``update_provider_tree`` for developers implementing this method in their own
virt drivers.

Background
----------
In the movement towards using placement for scheduling and resource management,
the virt driver method ``get_available_resource`` was initially superseded by
``get_inventory``, whereby the driver could specify its inventory in terms
understood by placement. In Queens, a ``get_traits`` driver method was added.
But ``get_inventory`` is limited to expressing only inventory (not traits or
aggregates). And both of these methods are limited to the resource provider
corresponding to the compute node.

Recent developments such as Nested Resource Providers necessitate the ability
for the virt driver to have deeper control over what the resource tracker
configures in placement on behalf of the compute node. This need is filled by
the virt driver method ``update_provider_tree`` and its consumption by the
resource tracker, allowing full control over the placement representation of
the compute node and its associated providers.

The Method
----------
``update_provider_tree`` accepts two parameters:

* A ``nova.compute.provider_tree.ProviderTree`` object representing all the
  providers in the tree associated with the compute node, and any sharing
  providers (those with the ``MISC_SHARES_VIA_AGGREGATE`` trait) associated via
  aggregate with any of those providers (but not *their* tree- or
  aggregate-associated providers), as currently known by placement. This
  object is fully owned by the ``update_provider_tree`` method, and can
  therefore be modified without locking/concurrency considerations. In other
  words, the parameter is passed *by reference* with the expectation that the
  virt driver will modify the object. Note, however, that it may contain
  providers not directly owned/controlled by the compute host. Care must be
  taken not to remove or modify such providers inadvertently. In addition,
  providers may be associated with traits and/or aggregates maintained by
  outside agents. The ``update_provider_tree`` method must therefore also be
  careful only to add/remove traits/aggregates it explicitly controls.
* String name of the compute node (i.e. ``ComputeNode.hypervisor_hostname``)
  for which the caller is requesting updated provider information. Drivers may
  use this to help identify the compute node provider in the ProviderTree.
  Drivers managing more than one node (e.g. ironic) may also use it as a cue to
  indicate which node is being processed by the caller.

The virt driver is expected to update the ProviderTree object with current
resource provider and inventory information. When the method returns, the
ProviderTree should represent the correct hierarchy of nested resource
providers associated with this compute node, as well as the inventory,
aggregates, and traits associated with those resource providers.

.. note:: Despite the name, a ProviderTree instance may in fact contain more
          than one tree. For purposes of this specification, the ProviderTree
          passed to ``update_provider_tree`` will contain:

          * the entire tree associated with the compute node; and
          * any sharing providers (those with the ``MISC_SHARES_VIA_AGGREGATE``
            trait) which are associated via aggregate with any of the providers
            in the compute node's tree. The sharing providers will be
            presented as lone roots in the ProviderTree, even if they happen to
            be part of a tree themselves.

          Consider the example below. ``SSP`` is a shared storage provider and
          ``BW1`` and ``BW2`` are shared bandwidth providers; all three have
          the ``MISC_SHARES_VIA_AGGREGATE`` trait::

                     CN1                 SHR_ROOT               CN2
                    /   \       agg1    /   /\     agg1        /   \
               NUMA1     NUMA2--------SSP--/--\-----------NUMA1     NUMA2
              /     \   /    \            /    \         /     \   /    \
            PF1    PF2 PF3   PF4--------BW1   BW2------PF1    PF2 PF3   PF4
                                 agg2             agg3

          When ``update_provider_tree`` is invoked for ``CN1``, it is passed a
          ProviderTree containing::

                     CN1 (root)
                    /   \       agg1
               NUMA1     NUMA2-------SSP (root)
              /     \   /    \
            PF1    PF2 PF3   PF4------BW1 (root)
                                 agg2

This method supersedes ``get_inventory`` and ``get_traits``: if this method is
implemented, neither ``get_inventory`` nor ``get_traits`` is used.

Driver implementations of ``update_provider_tree`` are expected to use public
``ProviderTree`` methods to effect changes to the provider tree passed in.
Some of the methods which may be useful are as follows:

* ``new_root``: Add a new root provider to the tree.
* ``new_child``: Add a new child under an existing provider.
* ``data``: Access information (name, UUID, parent, inventory, traits,
  aggregates) about a provider in the tree.
* ``remove``: Remove a provider **and its descendants** from the tree. Use
  caution in multiple-ownership scenarios.
* ``update_inventory``: Set the inventory for a provider.
* ``add_traits``, ``remove_traits``: Set/unset virt-owned traits for a
  provider.
* ``add_aggregates``, ``remove_aggregates``: Set/unset virt-owned aggregate
  associations for a provider.

.. note:: There is no supported mechanism for ``update_provider_tree`` to
          effect changes to allocations. This is intentional: in Nova,
          allocations are managed exclusively outside of virt. (Usually by the
          scheduler; sometimes - e.g. for migrations - by the conductor.)

Porting from get_inventory
~~~~~~~~~~~~~~~~~~~~~~~~~~
Virt driver developers wishing to move from ``get_inventory`` to
``update_provider_tree`` should use the ``ProviderTree.update_inventory``
method, specifying the compute node as the provider and the same inventory as
returned by ``get_inventory``. For example:

.. code::

  def get_inventory(self, nodename):
      inv_data = {
          'VCPU': { ... },
          'MEMORY_MB': { ... },
          'DISK_GB': { ... },
      }
      return inv_data

would become:

.. code::

  def update_provider_tree(self, provider_tree, nodename):
      inv_data = {
          'VCPU': { ... },
          'MEMORY_MB': { ... },
          'DISK_GB': { ... },
      }
      provider_tree.update_inventory(nodename, inv_data)

When reporting inventory for the standard resource classes ``VCPU``,
``MEMORY_MB`` and ``DISK_GB``, implementors of ``update_provider_tree`` may
need to set the ``allocation_ratio`` and ``reserved`` values in the
``inv_data`` dict based on configuration to reflect changes on the compute
for allocation ratios and reserved resource amounts back to the placement
service.

Porting from get_traits
~~~~~~~~~~~~~~~~~~~~~~~
To replace ``get_traits``, developers should use the
``ProviderTree.add_traits`` method, specifying the compute node as the
provider and the same traits as returned by ``get_traits``. For example:

.. code::

  def get_traits(self, nodename):
      traits = ['HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'CUSTOM_GOLD']
      return traits

would become:

.. code::

  def update_provider_tree(self, provider_tree, nodename):
      provider_tree.add_traits(
          nodename, 'HW_CPU_X86_AVX', 'HW_CPU_X86_AVX2', 'CUSTOM_GOLD')
