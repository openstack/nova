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


===================
Project Priorities
===================

Icehouse
--------

Tried requiring cores to sign up to review specific blueprints during
the blueprint approval process, but almost no one signed up so we abandoned
the idea in Juno.

Juno
------

* Poor prioritization of our 88 blueprints, attempts to get feedback via
  etherpads largely went unnoticed
* Implicit notion of what nova as a project would like to accomplish for the next
  release. But it was too implicit and everyone had a slightly different list
* Project priorities are not factored into the blueprint review process

Problem
--------

* Poor job at prioritizing. Our current process doesn't provide the nova team
  a good way to prioritize efforts. As a team we would like to identify and
  prioritize blueprints that can we deem as project priorities
* No easy way to communicate to contributors what the project as a whole
  thinks we should be working on for a given release, making it hard to
  focus our efforts in project priorities
* Difficult for contributors to understand the importance of work that isn't
  strictly about new features for new use cases

Kilo
-----

* Pick several project priority themes, in the form of use cases, to help us
  prioritize work

  * Generate list of improvement blueprints based on the themes
  * Produce rough draft of list going into summit and finalize the list at
    the summit
  * Publish list of project priorities and look for volunteers to work on them
* Update spec template to include

  * Specific use cases
  * State if the spec is project priority or not
* Keep an up to date list of project priority blueprints that need code review

  * List will be a YAML file so it is both human and machine readable
  * List will live in nova-specs
  * Support ability to build tools to consume this list
* Consumers of project priority and project priority blueprint lists:

  * Reviewers looking for direction of where to spend their blueprint review
    time.  If a large subset of nova-core doesn't use the project
    priorities it means the core team is not aligned properly and should
    revisit the list of project priorities
  * The blueprint approval team, to help find the right balance of blueprints
  * Contributors looking for something to work on
  * People looking for what they can expect in the next release

Note that the specific priorities for Kilo can be found here:
http://specs.openstack.org/openstack/nova-specs/priorities/kilo-priorities.html

Examples
---------

Project priorities:

* Stability. As a user I don't want things to randomly fail.
* Debugging. As an operator when something goes wrong, the logs should
  be helpful for debugging.
* Improved python client. As a user, I want a friendly python SDK and CLI. It
  should be easy to use as possible.
* Live upgrades. As an operator I want to be able to upgrade nova
  without any downtime.
* Fault tolerance. As an operator I don't want any single hardware or software
  failure to break nova.
* Performance/Scalability. As a operator I want nova to scale and perform well.

Project priority blueprints:

* Convert X to Objects (Live upgrades -- via minimal db downtime upgrades)
* Remove stacktraces from nova-api (Debugging)
* Improve usage of SQLAlchemy: https://wiki.openstack.org/wiki/Openstack_and_SQLAlchemy#ORM_Quick_Wins_Proof_of_Concept (Performance)
