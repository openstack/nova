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

from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields as obj_fields
from nova.virt import hardware


# TODO(berrange): Remove NovaObjectDictCompat
class InstanceNUMACell(base.NovaObject,
                       base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Add pagesize field
    # Version 1.2: Add cpu_pinning_raw and topology fields
    VERSION = '1.2'

    fields = {
        'id': obj_fields.IntegerField(),
        'cpuset': obj_fields.SetOfIntegersField(),
        'memory': obj_fields.IntegerField(),
        'pagesize': obj_fields.IntegerField(nullable=True),
        'cpu_topology': obj_fields.ObjectField('VirtCPUTopology',
                                               nullable=True),
        'cpu_pinning_raw': obj_fields.DictOfIntegersField(nullable=True)
        }

    obj_relationships = {
        'cpu_topology': [('1.2', '1.0')]
    }

    cpu_pinning = obj_fields.DictProxyField('cpu_pinning_raw')

    def __init__(self, **kwargs):
        super(InstanceNUMACell, self).__init__(**kwargs)
        if 'pagesize' not in kwargs:
            self.pagesize = None
            self.obj_reset_changes(['pagesize'])
        if 'cpu_topology' not in kwargs:
            self.cpu_topology = None
            self.obj_reset_changes(['cpu_topology'])
        if 'cpu_pinning' not in kwargs:
            self.cpu_pinning = None
            self.obj_reset_changes(['cpu_pinning_raw'])

    def __len__(self):
        return len(self.cpuset)

    def _to_dict(self):
        # NOTE(sahid): Used as legacy, could be renamed in
        # _legacy_to_dict_ to the future to avoid confusing.
        return {'cpus': hardware.format_cpu_spec(self.cpuset,
                                                 allow_ranges=False),
                'mem': {'total': self.memory},
                'id': self.id,
                'pagesize': self.pagesize}

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
        if self.cpu_topology:
            threads = self.cpu_topology.threads
        if threads == 1:
            threads = 0

        return map(set, zip(*[iter(cpu_list)] * threads))

    @property
    def cpu_pinning_requested(self):
        return self.cpu_pinning is not None

    def pin(self, vcpu, pcpu):
        if vcpu not in self.cpuset:
            return
        pinning_dict = self.cpu_pinning or {}
        pinning_dict[vcpu] = pcpu
        self.cpu_pinning = pinning_dict

    def pin_vcpus(self, *cpu_pairs):
        for vcpu, pcpu in cpu_pairs:
            self.pin(vcpu, pcpu)


# TODO(berrange): Remove NovaObjectDictCompat
class InstanceNUMATopology(base.NovaObject,
                           base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Takes into account pagesize
    VERSION = '1.1'

    fields = {
        # NOTE(danms): The 'id' field is no longer used and should be
        # removed in the future when convenient
        'id': obj_fields.IntegerField(),
        'instance_uuid': obj_fields.UUIDField(),
        'cells': obj_fields.ListOfObjectsField('InstanceNUMACell'),
        }

    obj_relationships = {
        'cells': [('1.0', '1.0')],
    }

    @classmethod
    def obj_from_primitive(cls, primitive):
        if 'nova_object.name' in primitive:
            obj_topology = super(InstanceNUMATopology, cls).obj_from_primitive(
                primitive)
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
    def create(self, context):
        self._save(context)

    # NOTE(ndipanov): We can't rename create and want to avoid version bump
    # as this needs to be backported to stable so this is not a @remotable
    # That's OK since we only call it from inside Instance.save() which is.
    def _save(self, context):
        values = {'numa_topology': self._to_json()}
        db.instance_extra_update_by_uuid(context, self.instance_uuid,
                                         values)
        self.obj_reset_changes()

    # NOTE(ndipanov): We want to avoid version bump
    # as this needs to be backported to stable so this is not a @remotable
    # That's OK since we only call it from inside Instance.save() which is.
    @classmethod
    def delete_by_instance_uuid(cls, context, instance_uuid):
        values = {'numa_topology': None}
        db.instance_extra_update_by_uuid(context, instance_uuid,
                                         values)

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

    def _to_dict(self):
        # NOTE(sahid): Used as legacy, could be renamed in _legacy_to_dict_
        # in the future to avoid confusing.
        return {'cells': [cell._to_dict() for cell in self.cells]}

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
