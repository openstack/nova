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

from nova import exception
from nova.objects import base
from nova.objects import fields as obj_fields
from nova.virt import hardware


@base.NovaObjectRegistry.register
class NUMACell(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added pinned_cpus and siblings fields
    # Version 1.2: Added mempages field
    # Version 1.3: Add network_metadata field
    # Version 1.4: Add pcpuset
    VERSION = '1.4'

    fields = {
        'id': obj_fields.IntegerField(read_only=True),
        'cpuset': obj_fields.SetOfIntegersField(),
        'pcpuset': obj_fields.SetOfIntegersField(),
        'memory': obj_fields.IntegerField(),
        'cpu_usage': obj_fields.IntegerField(default=0),
        'memory_usage': obj_fields.IntegerField(default=0),
        'pinned_cpus': obj_fields.SetOfIntegersField(),
        'siblings': obj_fields.ListOfSetsOfIntegersField(),
        'mempages': obj_fields.ListOfObjectsField('NUMAPagesTopology'),
        'network_metadata': obj_fields.ObjectField('NetworkMetadata'),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(NUMACell, self).obj_make_compatible(primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4):
            primitive.pop('pcpuset', None)
        if target_version < (1, 3):
            primitive.pop('network_metadata', None)

    def __eq__(self, other):
        return base.all_things_equal(self, other)

    def __ne__(self, other):
        return not (self == other)

    @property
    def free_pcpus(self):
        """Return available dedicated CPUs."""
        return self.pcpuset - self.pinned_cpus or set()

    @property
    def free_siblings(self):
        """Return available dedicated CPUs in their sibling set form."""
        return [sibling_set & self.free_pcpus for sibling_set in self.siblings]

    @property
    def avail_pcpus(self):
        """Return number of available dedicated CPUs."""
        return len(self.free_pcpus)

    @property
    def avail_memory(self):
        return self.memory - self.memory_usage

    @property
    def has_threads(self):
        """Check if SMT threads, a.k.a. HyperThreads, are present."""
        return any(len(sibling_set) > 1 for sibling_set in self.siblings)

    def pin_cpus(self, cpus):
        if cpus - self.pcpuset:
            raise exception.CPUPinningUnknown(requested=list(cpus),
                                              available=list(self.pcpuset))

        if self.pinned_cpus & cpus:
            available = list(self.pcpuset - self.pinned_cpus)
            raise exception.CPUPinningInvalid(requested=list(cpus),
                                              available=available)

        self.pinned_cpus |= cpus

    def unpin_cpus(self, cpus):
        if cpus - self.pcpuset:
            raise exception.CPUUnpinningUnknown(requested=list(cpus),
                                                available=list(self.pcpuset))

        if (self.pinned_cpus & cpus) != cpus:
            raise exception.CPUUnpinningInvalid(requested=list(cpus),
                                                available=list(
                                                    self.pinned_cpus))

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

    def can_fit_pagesize(self, pagesize, memory, use_free=True):
        """Returns whether memory can fit into a given pagesize.

        :param pagesize: a page size in KibB
        :param memory: a memory size asked to fit in KiB
        :param use_free: if true, assess based on free memory rather than total
            memory. This means overcommit is not allowed, which should be the
            case for hugepages since these are memlocked by the kernel and
            can't be swapped out.

        :returns: whether memory can fit in hugepages
        :raises: MemoryPageSizeNotSupported if page size not supported
        """
        for pages in self.mempages:
            avail_kb = pages.free_kb if use_free else pages.total_kb
            if pages.size_kb == pagesize:
                return memory <= avail_kb and (memory % pages.size_kb) == 0
        raise exception.MemoryPageSizeNotSupported(pagesize=pagesize)


@base.NovaObjectRegistry.register
class NUMAPagesTopology(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Adds reserved field
    VERSION = '1.1'

    fields = {
        'size_kb': obj_fields.IntegerField(),
        'total': obj_fields.IntegerField(),
        'used': obj_fields.IntegerField(default=0),
        'reserved': obj_fields.IntegerField(default=0),
        }

    def obj_make_compatible(self, primitive, target_version):
        super(NUMAPagesTopology, self).obj_make_compatible(primitive,
                                                           target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            primitive.pop('reserved', None)

    def __eq__(self, other):
        return base.all_things_equal(self, other)

    def __ne__(self, other):
        return not (self == other)

    @property
    def free(self):
        """Returns the number of avail pages."""
        if not self.obj_attr_is_set('reserved'):
            # In case where an old compute node is sharing resource to
            # an updated node we must ensure that this property is defined.
            self.reserved = 0
        return self.total - self.used - self.reserved

    @property
    def free_kb(self):
        """Returns the avail memory size in KiB."""
        return self.free * self.size_kb

    @property
    def total_kb(self):
        """Returns the total memory size in KiB."""
        return self.total * self.size_kb


@base.NovaObjectRegistry.register
class NUMATopology(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Update NUMACell to 1.1
    # Version 1.2: Update NUMACell to 1.2
    VERSION = '1.2'

    fields = {
        'cells': obj_fields.ListOfObjectsField('NUMACell'),
    }

    def __eq__(self, other):
        return base.all_things_equal(self, other)

    def __ne__(self, other):
        return not (self == other)

    @property
    def has_threads(self):
        """Check if any cell use SMT threads (a.k.a. Hyperthreads)"""
        return any(cell.has_threads for cell in self.cells)

    def _to_json(self):
        return jsonutils.dumps(self.obj_to_primitive())

    @classmethod
    def obj_from_db_obj(cls, db_obj):
        """Convert serialized representation to object.

        Deserialize instances of this object that have been stored as JSON
        blobs in the database.
        """
        return cls.obj_from_primitive(jsonutils.loads(db_obj))

    @classmethod
    def from_legacy_object(cls, primitive: str):
        """Convert a pre-Liberty object to a (serialized) real o.vo.

        :param primitive: A serialized representation of the legacy object.
        :returns: A serialized representation of the updated object.
        """
        topology = cls(
            cells=[
                NUMACell(
                    id=cell.get('id'),
                    cpuset=hardware.parse_cpu_spec(cell.get('cpus', '')),
                    cpu_usage=cell.get('cpu_usage', 0),
                    memory=cell.get('mem', {}).get('total', 0),
                    memory_usage=cell.get('mem', {}).get('used', 0),
                    mempages=[],
                    pinned_cpus=set(),
                    siblings=[],
                ) for cell in jsonutils.loads(primitive).get('cells', [])
            ],
        )
        return topology._to_json()

    def __len__(self):
        """Defined so that boolean testing works the same as for lists."""
        return len(self.cells)


@base.NovaObjectRegistry.register
class NUMATopologyLimits(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add network_metadata field
    VERSION = '1.1'

    fields = {
        'cpu_allocation_ratio': obj_fields.FloatField(),
        'ram_allocation_ratio': obj_fields.FloatField(),
        'network_metadata': obj_fields.ObjectField('NetworkMetadata'),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(NUMATopologyLimits, self).obj_make_compatible(primitive,
                                                            target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            primitive.pop('network_metadata', None)
