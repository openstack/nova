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

from nova import exception
from nova.objects import base
from nova.objects import fields
from nova.virt import hardware


def all_things_equal(obj_a, obj_b):
    for name in obj_a.fields:
        set_a = obj_a.obj_attr_is_set(name)
        set_b = obj_b.obj_attr_is_set(name)
        if set_a != set_b:
            return False
        elif not set_a:
            continue

        if getattr(obj_a, name) != getattr(obj_b, name):
                return False
    return True


@base.NovaObjectRegistry.register
class NUMACell(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added pinned_cpus and siblings fields
    # Version 1.2: Added mempages field
    VERSION = '1.2'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'cpuset': fields.SetOfIntegersField(),
        'memory': fields.IntegerField(),
        'cpu_usage': fields.IntegerField(default=0),
        'memory_usage': fields.IntegerField(default=0),
        'pinned_cpus': fields.SetOfIntegersField(),
        'siblings': fields.ListOfSetsOfIntegersField(),
        'mempages': fields.ListOfObjectsField('NUMAPagesTopology'),
        }

    def __eq__(self, other):
        return all_things_equal(self, other)

    def __ne__(self, other):
        return not (self == other)

    @property
    def free_cpus(self):
        return self.cpuset - self.pinned_cpus or set()

    @property
    def free_siblings(self):
        return [sibling_set & self.free_cpus
                for sibling_set in self.siblings]

    @property
    def avail_cpus(self):
        return len(self.free_cpus)

    @property
    def avail_memory(self):
        return self.memory - self.memory_usage

    def pin_cpus(self, cpus):
        if cpus - self.cpuset:
            raise exception.CPUPinningUnknown(requested=list(cpus),
                                              cpuset=list(self.pinned_cpus))
        if self.pinned_cpus & cpus:
            raise exception.CPUPinningInvalid(requested=list(cpus),
                                              pinned=list(self.pinned_cpus))
        self.pinned_cpus |= cpus

    def unpin_cpus(self, cpus):
        if cpus - self.cpuset:
            raise exception.CPUPinningUnknown(requested=list(cpus),
                                              cpuset=list(self.pinned_cpus))
        if (self.pinned_cpus & cpus) != cpus:
            raise exception.CPUPinningInvalid(requested=list(cpus),
                                              pinned=list(self.pinned_cpus))
        self.pinned_cpus -= cpus

    def pin_cpus_with_siblings(self, cpus):
        pin_siblings = set()
        for sib in self.siblings:
            if cpus & sib:
                pin_siblings.update(sib)
        self.pin_cpus(pin_siblings)

    def unpin_cpus_with_siblings(self, cpus):
        pin_siblings = set()
        for sib in self.siblings:
            if cpus & sib:
                pin_siblings.update(sib)
        self.unpin_cpus(pin_siblings)

    def _to_dict(self):
        return {
            'id': self.id,
            'cpus': hardware.format_cpu_spec(
                self.cpuset, allow_ranges=False),
            'mem': {
                'total': self.memory,
                'used': self.memory_usage},
            'cpu_usage': self.cpu_usage}

    @classmethod
    def _from_dict(cls, data_dict):
        cpuset = hardware.parse_cpu_spec(
            data_dict.get('cpus', ''))
        cpu_usage = data_dict.get('cpu_usage', 0)
        memory = data_dict.get('mem', {}).get('total', 0)
        memory_usage = data_dict.get('mem', {}).get('used', 0)
        cell_id = data_dict.get('id')
        return cls(id=cell_id, cpuset=cpuset, memory=memory,
                   cpu_usage=cpu_usage, memory_usage=memory_usage,
                   mempages=[], pinned_cpus=set([]), siblings=[])

    def can_fit_hugepages(self, pagesize, memory):
        """Returns whether memory can fit into hugepages size

        :param pagesize: a page size in KibB
        :param memory: a memory size asked to fit in KiB

        :returns: whether memory can fit in hugepages
        :raises: MemoryPageSizeNotSupported if page size not supported
        """
        for pages in self.mempages:
            if pages.size_kb == pagesize:
                return (memory <= pages.free_kb and
                        (memory % pages.size_kb) == 0)
        raise exception.MemoryPageSizeNotSupported(pagesize=pagesize)


@base.NovaObjectRegistry.register
class NUMAPagesTopology(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'size_kb': fields.IntegerField(),
        'total': fields.IntegerField(),
        'used': fields.IntegerField(default=0),
        }

    def __eq__(self, other):
        return all_things_equal(self, other)

    def __ne__(self, other):
        return not (self == other)

    @property
    def free(self):
        """Returns the number of avail pages."""
        return self.total - self.used

    @property
    def free_kb(self):
        """Returns the avail memory size in KiB."""
        return self.free * self.size_kb


@base.NovaObjectRegistry.register
class NUMATopology(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Update NUMACell to 1.1
    # Version 1.2: Update NUMACell to 1.2
    VERSION = '1.2'

    fields = {
        'cells': fields.ListOfObjectsField('NUMACell'),
        }

    @classmethod
    def obj_from_primitive(cls, primitive, context=None):
        if 'nova_object.name' in primitive:
            obj_topology = super(NUMATopology, cls).obj_from_primitive(
                primitive, context=context)
        else:
            # NOTE(sahid): This compatibility code needs to stay until we can
            # guarantee that there are no cases of the old format stored in
            # the database (or forever, if we can never guarantee that).
            obj_topology = NUMATopology._from_dict(primitive)
        return obj_topology

    def _to_json(self):
        return jsonutils.dumps(self.obj_to_primitive())

    @classmethod
    def obj_from_db_obj(cls, db_obj):
        return cls.obj_from_primitive(
            jsonutils.loads(db_obj))

    def __len__(self):
        """Defined so that boolean testing works the same as for lists."""
        return len(self.cells)

    def _to_dict(self):
        # TODO(sahid): needs to be removed.
        return {'cells': [cell._to_dict() for cell in self.cells]}

    @classmethod
    def _from_dict(cls, data_dict):
        return cls(cells=[
            NUMACell._from_dict(cell_dict)
            for cell_dict in data_dict.get('cells', [])])


@base.NovaObjectRegistry.register
class NUMATopologyLimits(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'cpu_allocation_ratio': fields.FloatField(),
        'ram_allocation_ratio': fields.FloatField(),
        }

    def to_dict_legacy(self, host_topology):
        cells = []
        for cell in host_topology.cells:
            cells.append(
                {'cpus': hardware.format_cpu_spec(
                    cell.cpuset, allow_ranges=False),
                 'mem': {'total': cell.memory,
                         'limit': cell.memory * self.ram_allocation_ratio},
                 'cpu_limit': len(cell.cpuset) * self.cpu_allocation_ratio,
                 'id': cell.id})
        return {'cells': cells}

    @classmethod
    def obj_from_db_obj(cls, db_obj):
        if 'nova_object.name' in db_obj:
            obj_topology = cls.obj_from_primitive(db_obj)
        else:
            # NOTE(sahid): This compatibility code needs to stay until we can
            # guarantee that all compute nodes are using RPC API => 3.40.
            cell = db_obj['cells'][0]
            ram_ratio = cell['mem']['limit'] / float(cell['mem']['total'])
            cpu_ratio = cell['cpu_limit'] / float(len(hardware.parse_cpu_spec(
                cell['cpus'])))
            obj_topology = NUMATopologyLimits(
                cpu_allocation_ratio=cpu_ratio,
                ram_allocation_ratio=ram_ratio)
        return obj_topology
