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

from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields
from nova.virt import hardware


class InstanceNUMACell(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'cpuset': fields.SetOfIntegersField(),
        'memory': fields.IntegerField(),
        }


class InstanceNUMATopology(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        # NOTE(danms): The 'id' field is no longer used and should be
        # removed in the future when convenient
        'id': fields.IntegerField(),
        'instance_uuid': fields.UUIDField(),
        'cells': fields.ListOfObjectsField('InstanceNUMACell'),
        }

    @classmethod
    def obj_from_topology(cls, topology):
        if not isinstance(topology, hardware.VirtNUMAInstanceTopology):
            raise exception.ObjectActionError(action='obj_from_topology',
                                              reason='invalid topology class')
        if topology:
            cells = []
            for topocell in topology.cells:
                cell = InstanceNUMACell(id=topocell.id, cpuset=topocell.cpuset,
                                        memory=topocell.memory)
                cells.append(cell)
            return cls(cells=cells)

    def topology_from_obj(self):
        cells = []
        for objcell in self.cells:
            cell = hardware.VirtNUMATopologyCell(objcell.id, objcell.cpuset,
                                                 objcell.memory)
            cells.append(cell)
        return hardware.VirtNUMAInstanceTopology(cells=cells)

    @base.remotable
    def create(self, context):
        topology = self.topology_from_obj()
        if not topology:
            return
        values = {'numa_topology': topology.to_json()}
        db.instance_extra_update_by_uuid(context, self.instance_uuid,
                                         values)
        self.obj_reset_changes()

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_topology = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid)
        if not db_topology:
            raise exception.NumaTopologyNotFound(instance_uuid=instance_uuid)

        if db_topology['numa_topology'] is None:
            return None

        topo = hardware.VirtNUMAInstanceTopology.from_json(
                db_topology['numa_topology'])
        obj_topology = cls.obj_from_topology(topo)
        obj_topology.id = db_topology['id']
        obj_topology.instance_uuid = db_topology['instance_uuid']
        # NOTE (ndipanov) not really needed as we never save, but left for
        # consistency
        obj_topology.obj_reset_changes()
        return obj_topology
