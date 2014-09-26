==================
Blueprints in Kilo
==================

===========================
When is a blueprint needed?
===========================

Juno
-----

Every new feature needs a blueprint, and all blueprints need a spec. If the
blueprint is small, then the spec should be small. We added the specs
workflow to help improve the design discussion part of blueprints, but
are using it as a documentation tool as well.


Problem
--------

The specs repo is very good for hashing out design, but if a new feature
doesn't need any design discussion, requiring a spec is a significant overhead.
If the spec is just used for documentation and not design discussion, we are
adding a whole extra round of reviewing when the documentation can just be done
in the commit message.

Kilo
-----

A spec is needed for any feature that requires a design discussion. All
features need a blueprint but not all blueprints require a spec.

If a new feature is straightforward enough that it doesn't need any design
discussion, then no spec is required. In order to provide the sort of
documentation that would otherwise be provided via a spec, the commit
message should include a ``DocImpact`` flag and a thorough description
of the feature from a user/operator perspective.

Guidelines for when a feature doesn't need a spec.

* Is the feature a single self contained change?

  * If the feature touches code all over the place, it probably should have
    a design discussion.
  * If the feature is big enough that it needs more then one commit, it
    probably should have a design discussion.
* Not an API change.

  * API changes always require a design discussion.


Examples
---------

Juno blueprints where no spec would be needed in Kilo:

* backportable-db-migrations-juno.rst

  * no discussion needed, this is now standard practice
* add-all-in-list-operator-to-extra-spec-ops.rst

  * Trivial self contained change
* hyper-v-console-log.rst

  * self contained, straight forward feature parity fix
* hyper-v-soft-reboot.rst

  * self contained, straight forward feature parity fix
* io-ops-weight.rst

  * self contained, both the motivation and usage details are easily explained
    in a commit message
* per-aggregate-filters.rst

  * self contained, adds new filters similar to ones we already have
* restrict-image-isolation-with-defined-keys.rst

  * self contained improvement to a scheduler filter

Juno blueprints where a spec would still be needed in Kilo:

* add-ironic-driver.rst
* config-drive-image-property.rst
* enabled-qemu-memballoon-stats.rst
* db2-database.rst
* cross-service-request-id.rst
* clean-logs.rst
* i18n-enablement.rst
* instance-network-info-hook.rst
* encryption-with-barbican.rst
* juno-slaveification.rst
* extensible-resource-tracking.rst
* cold-migration-with-target.rst
* allow-image-to-be-specified-during-rescue.rst
* add-differencing-vhdx-resize-support.rst
* add-virtio-scsi-bus-for-bdm.rst
* compute-manager-objects-juno.rst
* allocation-ratio-to-resource-tracker.rst
* better-support-for-multiple-networks.rst
* nova-pagination.rst
* convert_ec2_api_to_use_nova_objects.rst
* make-resource-tracker-use-objects.rst
* object-subclassing.rst
* virt-objects-juno.rst
* scheduler-lib.rst
* return-status-for-hypervisor-node.rst
* server-count-api.rst
* server-group-quotas.rst
* ec2-volume-and-snapshot-tags.rst
* enforce-unique-instance-uuid-in-db.rst
* find-host-and-evacuate-instance.rst
* input-output-based-numa-scheduling.rst
* libvirt-domain-listing-speedup.rst
* libvirt-disk-discard-option.rst
* libvirt-driver-class-refactor.rst
* libvirt-lxc-user-namespaces.rst
* libvirt-driver-domain-metadata.rst
* libvirt-sheepdog-backed-instances.rst
* libvirt-start-lxc-from-block-devices.rst
* libvirt-volume-snap-network-disk.rst
* log-request-id-mappings.rst
* lvm-ephemeral-storage-encryption.rst
* v2-on-v3-api.rst
* v3-api-schema.rst
* v3-diagnostics.rst
* tag-instances.rst
* support-cinderclient-v2.rst
* use-oslo-vmware.rst
* return-all-servers-during-multiple-create.rst
* remove-cast-to-schedule-run-instance.rst
* persistent-resource-claim.rst
* serial-ports.rst
* servers-list-support-multi-status.rst
* xenapi-vcpu-topology.rst
* selecting-subnet-when-creating-vm.rst
* refactor-network-api.rst
* migrate-libvirt-volumes.rst
* move-prep-resize-to-conductor.rst
* nfv-multiple-if-1-net.rst
* on-demand-compute-update.rst
* pci-passthrough-sriov.rst
* quiesced-image-snapshots-with-qemu-guest-agent.rst
* rbd-clone-image-handler.rst
* rescue-attach-all-disks.rst
* standardize-nova-image.rst
* string-field-max-length.rst
* support-console-log-migration.rst
* use-libvirt-storage-pools.rst
* user-defined-shutdown.rst
* vif-vhostuser.rst
* virt-driver-cpu-pinning.rst
* virt-driver-large-pages.rst
* virt-driver-numa-placement.rst
* virt-driver-vcpu-topology.rst
* vmware-driver-ova-support.rst
* vmware-ephemeral-disk-support.rst
* vmware-hot-plug.rst
* vmware-spbm-support.rst
* vmware-vsan-support.rst
* websocket-proxy-to-host-security.rst
* xenapi-set-ipxe-url-as-img-metadata.rst

