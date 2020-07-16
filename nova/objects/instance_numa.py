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

from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova.db import api as db
from nova import exception
from nova.i18n import _
from nova.objects import base
from nova.objects import fields as obj_fields
from nova.virt import hardware


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
                    reason=_('mixed instance is not supported in version %s') %
                           target_version)

        # NOTE(huaqiang): Since version 1.5, 'cpuset' is modified to track the
        # unpinned CPUs only, with pinned CPUs tracked via 'pcpuset' instead.
        # For a backward compatibility, move the 'dedicated' instance CPU list
        # from 'pcpuset' to 'cpuset'.
        if target_version < (1, 5):
            if (primitive['cpu_policy'] ==
                    obj_fields.CPUAllocationPolicy.DEDICATED):
                primitive['cpuset'] = primitive['pcpuset']
            primitive.pop('pcpuset', None)

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
            cls._migrate_legacy_dedicated_instance_cpuset(
                context, instance_uuid, obj)
        else:
            obj = cls._migrate_legacy_object(context, instance_uuid, primitive)

        return obj

    # TODO(huaqiang): Remove after Wallaby once we are sure these objects have
    # been loaded at least once.
    @classmethod
    def _migrate_legacy_dedicated_instance_cpuset(cls, context, instance_uuid,
                                                  obj):
        # NOTE(huaqiang): We may meet some topology object with the old version
        # 'InstanceNUMACell' cells, in that case, the 'dedicated' CPU is kept
        # in 'InstanceNUMACell.cpuset' field, but it should be kept in
        # 'InstanceNUMACell.pcpuset' field since Victoria. Making an upgrade
        # and persisting to database.
        update_db = False
        for cell in obj.cells:
            if len(cell.cpuset) == 0:
                continue

            if cell.cpu_policy != obj_fields.CPUAllocationPolicy.DEDICATED:
                continue

            cell.pcpuset = cell.cpuset
            cell.cpuset = set()
            update_db = True

        if update_db:
            db_obj = jsonutils.dumps(obj.obj_to_primitive())
            values = {
                'numa_topology': db_obj,
            }
            db.instance_extra_update_by_uuid(context, instance_uuid,
                                             values)

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
