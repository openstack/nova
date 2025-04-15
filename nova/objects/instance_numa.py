#    Copyright 2014 Red Hat Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import itertools

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova.db.main import api as db
from nova import exception
from nova.i18n import _
from nova.objects import base
from nova.objects import fields as obj_fields
from nova.virt import hardware

LOG = logging.getLogger(__name__)


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceNUMACell(base.NovaEphemeralObject,
                       base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Add pagesize field
    # Version 1.2: Add cpu_pinning_raw and topology fields
    # Version 1.3: Add cpu_policy and cpu_thread_policy fields
    # Version 1.4: Add cpuset_reserved field
    # Version 1.5: Add pcpuset field
    # Version 1.6: Add 'mixed' to cpu_policy field
    VERSION = '1.6'

    def obj_make_compatible(self, primitive, target_version):
        super(InstanceNUMACell, self).obj_make_compatible(primitive,
                                                          target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        # Instance with a 'mixed' CPU policy could not provide a backward
        # compatibility.
        if target_version < (1, 6):
            if primitive['cpu_policy'] == obj_fields.CPUAllocationPolicy.MIXED:
                raise exception.ObjectActionError(
                    action='obj_make_compatible',
                    reason=_(
                        '{policy} policy is not supported in '
                        'version {version}'
                    ).format(policy=primitive['cpu_policy'],
                             version=target_version))

        # NOTE(huaqiang): Since version 1.5, 'cpuset' is modified to track the
        # unpinned CPUs only, with pinned CPUs tracked via 'pcpuset' instead.
        # For a backward compatibility, move the 'dedicated' instance CPU list
        # from 'pcpuset' to 'cpuset'.
        if target_version < (1, 5):
            if (primitive['cpu_policy'] ==
                    obj_fields.CPUAllocationPolicy.DEDICATED):
                primitive['cpuset'] = primitive['pcpuset']
            primitive.pop('pcpuset', None)
            LOG.warning(
                f'Downgrading InstanceNUMACell to version {target_version} '
                f'may cause the loss of pinned CPUs if mixing different '
                f'verisons of nova on different hosts. This should not '
                f'happen on any supported version after Victoria.')

        if target_version < (1, 4):
            primitive.pop('cpuset_reserved', None)

        if target_version < (1, 3):
            primitive.pop('cpu_policy', None)
            primitive.pop('cpu_thread_policy', None)

    fields = {
        'id': obj_fields.IntegerField(),
        'cpuset': obj_fields.SetOfIntegersField(),
        'pcpuset': obj_fields.SetOfIntegersField(),
        # These physical CPUs are reserved for use by the hypervisor
        'cpuset_reserved': obj_fields.SetOfIntegersField(nullable=True,
                                                         default=None),
        'memory': obj_fields.IntegerField(),
        'pagesize': obj_fields.IntegerField(nullable=True,
                                            default=None),
        # TODO(sean-k-mooney): This is no longer used and should be
        # removed in v2
        'cpu_topology': obj_fields.ObjectField('VirtCPUTopology',
                                               nullable=True),
        'cpu_pinning_raw': obj_fields.DictOfIntegersField(nullable=True,
                                                          default=None),
        'cpu_policy': obj_fields.CPUAllocationPolicyField(nullable=True,
                                                          default=None),
        'cpu_thread_policy': obj_fields.CPUThreadAllocationPolicyField(
            nullable=True, default=None),
    }

    cpu_pinning = obj_fields.DictProxyField('cpu_pinning_raw')

    def __len__(self):
        return len(self.total_cpus)

    @property
    def total_cpus(self):
        return self.cpuset | self.pcpuset

    @property
    def siblings(self):
        cpu_list = sorted(list(self.total_cpus))

        threads = 0
        if ('cpu_topology' in self) and self.cpu_topology:
            threads = self.cpu_topology.threads
        if threads == 1:
            threads = 0

        return list(map(set, zip(*[iter(cpu_list)] * threads)))

    def pin(self, vcpu, pcpu):
        if vcpu not in self.pcpuset:
            return
        pinning_dict = self.cpu_pinning or {}
        pinning_dict[vcpu] = pcpu
        self.cpu_pinning = pinning_dict

    def pin_vcpus(self, *cpu_pairs):
        for vcpu, pcpu in cpu_pairs:
            self.pin(vcpu, pcpu)

    def clear_host_pinning(self):
        """Clear any data related to how this cell is pinned to the host.

        Needed for aborting claims as we do not want to keep stale data around.
        """
        self.id = -1
        self.cpu_pinning = {}
        return self


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceNUMATopology(base.NovaObject,
                           base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Takes into account pagesize
    # Version 1.2: InstanceNUMACell 1.2
    # Version 1.3: Add emulator threads policy
    VERSION = '1.3'

    def obj_make_compatible(self, primitive, target_version):
        super(InstanceNUMATopology, self).obj_make_compatible(primitive,
                                                              target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 3):
            primitive.pop('emulator_threads_policy', None)

    fields = {
        # NOTE(danms): The 'id' field is no longer used and should be
        # removed in the future when convenient
        'id': obj_fields.IntegerField(),
        'instance_uuid': obj_fields.UUIDField(),
        'cells': obj_fields.ListOfObjectsField('InstanceNUMACell'),
        'emulator_threads_policy': (
            obj_fields.CPUEmulatorThreadsPolicyField(nullable=True)),
        }

    @classmethod
    def obj_from_db_obj(cls, context, instance_uuid, db_obj):
        primitive = jsonutils.loads(db_obj)

        if 'nova_object.name' in primitive:
            obj = cls.obj_from_primitive(primitive)
            updated = cls._migrate_legacy_dedicated_instance_cpuset(obj)
            if updated:
                cls._save_migrated_cpuset_to_instance_extra(
                    context, obj, instance_uuid)
        else:
            obj = cls._migrate_legacy_object(context, instance_uuid, primitive)

        return obj

    # TODO(huaqiang): Remove after Wallaby once we are sure these objects have
    # been loaded at least once.
    @classmethod
    def _migrate_legacy_dedicated_instance_cpuset(cls, obj):
        # NOTE(huaqiang): We may meet some topology object with the old version
        # 'InstanceNUMACell' cells, in that case, the 'dedicated' CPU is kept
        # in 'InstanceNUMACell.cpuset' field, but it should be kept in
        # 'InstanceNUMACell.pcpuset' field since Victoria. Making an upgrade
        # here but letting the caller persist the result if needed as we
        # don't know which table the InstanceNUMACell is coming from. It can
        # come from instance_extra or request_spec too.
        update_db = False
        for cell in obj.cells:
            version = versionutils.convert_version_to_tuple(cell.VERSION)

            if version < (1, 4):
                LOG.warning(
                    "InstanceNUMACell %s with version %s for instance %s has "
                    "too old version in the DB, don't know how to update, "
                    "ignoring.", cell, cell.VERSION, obj.instance_uuid)
                continue

            if (version >= (1, 5) and
                cell.cpu_policy == obj_fields.CPUAllocationPolicy.DEDICATED and
                (cell.cpuset or not cell.pcpuset)
            ):
                LOG.warning(
                    "InstanceNUMACell %s with version %s is inconsistent as "
                    "the version is 1.5 or greater, cpu_policy is dedicated, "
                    "but cpuset is not empty or pcpuset is empty.",
                    cell, cell.VERSION)
                continue

            # NOTE(gibi): The data migration between 1.4. and 1.5 populates the
            # pcpuset field that is new in version 1.5. However below we update
            # the object version to 1.6 directly. This is intentional. The
            # version 1.6 introduced a new possible value 'mixed' for the
            # cpu_policy field. As that is a forward compatible change we don't
            # have a specific data migration for it. But we also don't have an
            # automated way to update old object versions from 1.5 to 1.6. So
            # we do it here just to avoid inconsistency between data and
            # version in the DB.
            if version < (1, 6):
                if cell.cpu_policy == obj_fields.CPUAllocationPolicy.DEDICATED:
                    if "pcpuset" not in cell or not cell.pcpuset:
                        # this cell was never migrated to 1.6, migrate it.
                        cell.pcpuset = cell.cpuset
                        cell.cpuset = set()
                        cell.VERSION = '1.6'
                        update_db = True
                    else:
                        # This data was already migrated to 1.6 format but the
                        # version string wasn't updated to 1.6. This happened
                        # before the fix
                        # https://bugs.launchpad.net/nova/+bug/2097360
                        # Only update the version string.
                        cell.VERSION = '1.6'
                        update_db = True
                elif cell.cpu_policy in (
                        None, obj_fields.CPUAllocationPolicy.SHARED):
                    # no data migration needed just add the new field and
                    # stamp the new version in the DB
                    cell.pcpuset = set()
                    cell.VERSION = '1.6'
                    update_db = True
                else:  # obj_fields.CPUAllocationPolicy.MIXED
                    # This means the cell data already got updated to the 1.6
                    # content as MIXED only supported with 1.6 but the version
                    # was not updated to 1.6.
                    # We should not do the data migration as that would trample
                    # the pcpuset field. Just stamp the 1.6 version in the DB
                    # and hope for the best.
                    LOG.warning(
                        "InstanceNUMACell %s with version %s for instance %s "
                        "has older than 1.6 version in the DB but using the "
                        "1.6 feature CPUAllocationPolicy.MIXED. So nova "
                        "assumes that the data is in 1.6 format and only the "
                        "version string is old. Correcting the version string "
                        "in the DB.", cell, cell.VERSION, obj.instance_uuid)
                    cell.VERSION = '1.6'
                    update_db = True

            # When the next ovo version 1.7 is added it needs to be handed
            # here to do any migration if needed and to ensure the version in
            # the DB is stamped to 1.7

        return update_db

    # TODO(huaqiang): Remove after Yoga once we are sure these objects have
    # been loaded at least once.
    @classmethod
    def _save_migrated_cpuset_to_instance_extra(
        cls, context, obj, instance_uuid
    ):
        db_obj = jsonutils.dumps(obj.obj_to_primitive())
        values = {
            'numa_topology': db_obj,
        }
        db.instance_extra_update_by_uuid(
            context, instance_uuid, values)

    # TODO(stephenfin): Remove in X or later, once this has bedded in
    @classmethod
    def _migrate_legacy_object(cls, context, instance_uuid, primitive):
        """Convert a pre-Liberty object to a real o.vo.

        Handle an unversioned object created prior to Liberty, by transforming
        to a versioned object and saving back the serialized version of this.

        :param context: RequestContext
        :param instance_uuid: The UUID of the instance this topology is
            associated with.
        :param primitive: A serialized representation of the legacy object.
        :returns: A serialized representation of the updated object.
        """
        obj = cls(
            instance_uuid=instance_uuid,
            cells=[
                InstanceNUMACell(
                    id=cell.get('id'),
                    cpuset=hardware.parse_cpu_spec(cell.get('cpus', '')),
                    pcpuset=set(),
                    memory=cell.get('mem', {}).get('total', 0),
                    pagesize=cell.get('pagesize'),
                ) for cell in primitive.get('cells', [])
            ],
        )
        db_obj = jsonutils.dumps(obj.obj_to_primitive())
        values = {
            'numa_topology': db_obj,
        }
        db.instance_extra_update_by_uuid(context, instance_uuid, values)
        return obj

    # TODO(ndipanov) Remove this method on the major version bump to 2.0
    @base.remotable
    def create(self):
        values = {'numa_topology': self._to_json()}
        db.instance_extra_update_by_uuid(self._context, self.instance_uuid,
                                         values)
        self.obj_reset_changes()

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_extra = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid, columns=['numa_topology'])
        if not db_extra:
            raise exception.NumaTopologyNotFound(instance_uuid=instance_uuid)

        if db_extra['numa_topology'] is None:
            return None

        return cls.obj_from_db_obj(
            context, instance_uuid, db_extra['numa_topology'])

    def _to_json(self):
        return jsonutils.dumps(self.obj_to_primitive())

    def __len__(self):
        """Defined so that boolean testing works the same as for lists."""
        return len(self.cells)

    # TODO(stephenfin): We should add a real 'cpu_policy' field on this object
    # and deprecate the one found on the cell
    @property
    def cpu_policy(self):
        cpu_policy = set(cell.cpu_policy for cell in self.cells)
        if len(cpu_policy) > 1:
            # NOTE(stephenfin): This should never happen in real life; it's to
            # prevent programmer error.
            raise exception.InternalError(
                'Instance NUMA cells must have the same CPU policy.'
            )
        return cpu_policy.pop()

    @property
    def cpu_pinning(self):
        """Return a set of all host CPUs this NUMATopology is pinned to."""
        return set(itertools.chain.from_iterable([
            cell.cpu_pinning.values() for cell in self.cells
            if cell.cpu_pinning]))

    @property
    def cpuset_reserved(self):
        return set(itertools.chain.from_iterable([
            cell.cpuset_reserved for cell in self.cells
            if cell.cpuset_reserved]))

    def clear_host_pinning(self):
        """Clear any data related to how instance is pinned to the host.

        Needed for aborting claims as we do not want to keep stale data around.
        """
        for cell in self.cells:
            cell.clear_host_pinning()
        return self

    @property
    def emulator_threads_isolated(self):
        """Determines whether emulator threads should be isolated"""
        return (self.obj_attr_is_set('emulator_threads_policy') and
                (self.emulator_threads_policy ==
                 obj_fields.CPUEmulatorThreadsPolicy.ISOLATE))
