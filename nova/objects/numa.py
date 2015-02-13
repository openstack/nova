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


# TODO(berrange): Remove NovaObjectDictCompat
class NUMACell(base.NovaObject,
               base.NovaObjectDictCompat):
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

    obj_relationships = {
        'mempages': [('1.2', '1.0')]
    }

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
        if self.pinned_cpus & cpus:
            raise exception.CPUPinningInvalid(requested=list(cpus),
                                              pinned=list(self.pinned_cpus))
        self.pinned_cpus |= cpus

    def unpin_cpus(self, cpus):
        if (self.pinned_cpus & cpus) != cpus:
            raise exception.CPUPinningInvalid(requested=list(cpus),
                                              pinned=list(self.pinned_cpus))
        self.pinned_cpus -= cpus

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


# TODO(berrange): Remove NovaObjectDictCompat
class NUMAPagesTopology(base.NovaObject,
                        base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'size_kb': fields.IntegerField(),
        'total': fields.IntegerField(),
        'used': fields.IntegerField(default=0),
        }

    @property
    def free(self):
        """Returns the number of avail pages."""
        return self.total - self.used

    @property
    def free_kb(self):
        """Returns the avail memory size in KiB."""
        return self.free * self.size_kb


# TODO(berrange): Remove NovaObjectDictCompat
class NUMATopology(base.NovaObject,
                   base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Update NUMACell to 1.1
    # Version 1.2: Update NUMACell to 1.2
    VERSION = '1.2'

    fields = {
        'cells': fields.ListOfObjectsField('NUMACell'),
        }

    obj_relationships = {
        'cells': [('1.0', '1.0'), ('1.1', '1.1'), ('1.2', '1.2')]
    }

    @classmethod
    def obj_from_primitive(cls, primitive):
        if 'nova_object.name' in primitive:
            obj_topology = super(NUMATopology, cls).obj_from_primitive(
                primitive)
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
