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

from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova.db import api as db
from nova import exception
from nova.objects import base
from nova.objects import fields as obj_fields
from nova.virt import hardware


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceNUMACell(base.NovaObject,
                       base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Add pagesize field
    # Version 1.2: Add cpu_pinning_raw and topology fields
    # Version 1.3: Add cpu_policy and cpu_thread_policy fields
    # Version 1.4: Add cpuset_reserved field
    VERSION = '1.4'

    def obj_make_compatible(self, primitive, target_version):
        super(InstanceNUMACell, self).obj_make_compatible(primitive,
                                                        target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4):
            primitive.pop('cpuset_reserved', None)

        if target_version < (1, 3):
            primitive.pop('cpu_policy', None)
            primitive.pop('cpu_thread_policy', None)

    fields = {
        'id': obj_fields.IntegerField(),
        'cpuset': obj_fields.SetOfIntegersField(),
        'memory': obj_fields.IntegerField(),
        'pagesize': obj_fields.IntegerField(nullable=True),
        'cpu_topology': obj_fields.ObjectField('VirtCPUTopology',
                                               nullable=True),
        'cpu_pinning_raw': obj_fields.DictOfIntegersField(nullable=True),
        'cpu_policy': obj_fields.CPUAllocationPolicyField(nullable=True),
        'cpu_thread_policy': obj_fields.CPUThreadAllocationPolicyField(
            nullable=True),
        # These physical CPUs are reserved for use by the hypervisor
        'cpuset_reserved': obj_fields.SetOfIntegersField(nullable=True),
    }

    cpu_pinning = obj_fields.DictProxyField('cpu_pinning_raw')

    def __init__(self, **kwargs):
        super(InstanceNUMACell, self).__init__(**kwargs)
        if 'pagesize' not in kwargs:
            self.pagesize = None
            self.obj_reset_changes(['pagesize'])
        if 'cpu_pinning' not in kwargs:
            self.cpu_pinning = None
            self.obj_reset_changes(['cpu_pinning_raw'])
        if 'cpu_policy' not in kwargs:
            self.cpu_policy = None
            self.obj_reset_changes(['cpu_policy'])
        if 'cpu_thread_policy' not in kwargs:
            self.cpu_thread_policy = None
            self.obj_reset_changes(['cpu_thread_policy'])
        if 'cpuset_reserved' not in kwargs:
            self.cpuset_reserved = None
            self.obj_reset_changes(['cpuset_reserved'])

    def __len__(self):
        return len(self.cpuset)

    @classmethod
    def _from_dict(cls, data_dict):
        # NOTE(sahid): Used as legacy, could be renamed in
        # _legacy_from_dict_ to the future to avoid confusing.
        cpuset = hardware.parse_cpu_spec(data_dict.get('cpus', ''))
        memory = data_dict.get('mem', {}).get('total', 0)
        cell_id = data_dict.get('id')
        pagesize = data_dict.get('pagesize')
        return cls(id=cell_id, cpuset=cpuset,
                   memory=memory, pagesize=pagesize)

    @property
    def siblings(self):
        cpu_list = sorted(list(self.cpuset))

        threads = 0
        if ('cpu_topology' in self) and self.cpu_topology:
            threads = self.cpu_topology.threads
        if threads == 1:
            threads = 0

        return list(map(set, zip(*[iter(cpu_list)] * threads)))

    @property
    def cpu_pinning_requested(self):
        return self.cpu_policy == obj_fields.CPUAllocationPolicy.DEDICATED

    def pin(self, vcpu, pcpu):
        if vcpu not in self.cpuset:
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
    def obj_from_primitive(cls, primitive, context=None):
        if 'nova_object.name' in primitive:
            obj_topology = super(InstanceNUMATopology, cls).obj_from_primitive(
                primitive, context=None)
        else:
            # NOTE(sahid): This compatibility code needs to stay until we can
            # guarantee that there are no cases of the old format stored in
            # the database (or forever, if we can never guarantee that).
            obj_topology = InstanceNUMATopology._from_dict(primitive)
            obj_topology.id = 0
        return obj_topology

    @classmethod
    def obj_from_db_obj(cls, instance_uuid, db_obj):
        primitive = jsonutils.loads(db_obj)
        obj_topology = cls.obj_from_primitive(primitive)

        if 'nova_object.name' not in db_obj:
            obj_topology.instance_uuid = instance_uuid
            # No benefit to store a list of changed fields
            obj_topology.obj_reset_changes()

        return obj_topology

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

        return cls.obj_from_db_obj(instance_uuid, db_extra['numa_topology'])

    def _to_json(self):
        return jsonutils.dumps(self.obj_to_primitive())

    def __len__(self):
        """Defined so that boolean testing works the same as for lists."""
        return len(self.cells)

    @classmethod
    def _from_dict(cls, data_dict):
        # NOTE(sahid): Used as legacy, could be renamed in _legacy_from_dict_
        # in the future to avoid confusing.
        return cls(cells=[
            InstanceNUMACell._from_dict(cell_dict)
            for cell_dict in data_dict.get('cells', [])])

    @property
    def cpu_pinning_requested(self):
        return all(cell.cpu_pinning_requested for cell in self.cells)

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
        return (self.obj_attr_is_set('emulator_threads_policy')
                and (self.emulator_threads_policy
                     == obj_fields.CPUEmulatorThreadsPolicy.ISOLATE))
