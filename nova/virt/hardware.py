# Copyright 2014 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import collections
import itertools

from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import units
import six

from nova import context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.openstack.common import log as logging

virt_cpu_opts = [
    cfg.StrOpt('vcpu_pin_set',
                help='Defines which pcpus that instance vcpus can use. '
               'For example, "4-12,^8,15"'),
]

CONF = cfg.CONF
CONF.register_opts(virt_cpu_opts)

LOG = logging.getLogger(__name__)

MEMPAGES_SMALL = -1
MEMPAGES_LARGE = -2
MEMPAGES_ANY = -3


def get_vcpu_pin_set():
    """Parsing vcpu_pin_set config.

    Returns a set of pcpu ids can be used by instances.
    """
    if not CONF.vcpu_pin_set:
        return None

    cpuset_ids = parse_cpu_spec(CONF.vcpu_pin_set)
    if not cpuset_ids:
        raise exception.Invalid(_("No CPUs available after parsing %r") %
                                CONF.vcpu_pin_set)
    return cpuset_ids


def parse_cpu_spec(spec):
    """Parse a CPU set specification.

    :param spec: cpu set string eg "1-4,^3,6"

    Each element in the list is either a single
    CPU number, a range of CPU numbers, or a
    caret followed by a CPU number to be excluded
    from a previous range.

    :returns: a set of CPU indexes
    """

    cpuset_ids = set()
    cpuset_reject_ids = set()
    for rule in spec.split(','):
        rule = rule.strip()
        # Handle multi ','
        if len(rule) < 1:
            continue
        # Note the count limit in the .split() call
        range_parts = rule.split('-', 1)
        if len(range_parts) > 1:
            # So, this was a range; start by converting the parts to ints
            try:
                start, end = [int(p.strip()) for p in range_parts]
            except ValueError:
                raise exception.Invalid(_("Invalid range expression %r")
                                        % rule)
            # Make sure it's a valid range
            if start > end:
                raise exception.Invalid(_("Invalid range expression %r")
                                        % rule)
            # Add available CPU ids to set
            cpuset_ids |= set(range(start, end + 1))
        elif rule[0] == '^':
            # Not a range, the rule is an exclusion rule; convert to int
            try:
                cpuset_reject_ids.add(int(rule[1:].strip()))
            except ValueError:
                raise exception.Invalid(_("Invalid exclusion "
                                          "expression %r") % rule)
        else:
            # OK, a single CPU to include; convert to int
            try:
                cpuset_ids.add(int(rule))
            except ValueError:
                raise exception.Invalid(_("Invalid inclusion "
                                          "expression %r") % rule)

    # Use sets to handle the exclusion rules for us
    cpuset_ids -= cpuset_reject_ids

    return cpuset_ids


def format_cpu_spec(cpuset, allow_ranges=True):
    """Format a libvirt CPU range specification.

    :param cpuset: set (or list) of CPU indexes

    Format a set/list of CPU indexes as a libvirt CPU
    range specification. It allow_ranges is true, it
    will try to detect continuous ranges of CPUs,
    otherwise it will just list each CPU index explicitly.

    :returns: a formatted CPU range string
    """

    # We attempt to detect ranges, but don't bother with
    # trying to do range negations to minimize the overall
    # spec string length
    if allow_ranges:
        ranges = []
        previndex = None
        for cpuindex in sorted(cpuset):
            if previndex is None or previndex != (cpuindex - 1):
                ranges.append([])
            ranges[-1].append(cpuindex)
            previndex = cpuindex

        parts = []
        for entry in ranges:
            if len(entry) == 1:
                parts.append(str(entry[0]))
            else:
                parts.append("%d-%d" % (entry[0], entry[len(entry) - 1]))
        return ",".join(parts)
    else:
        return ",".join(str(id) for id in sorted(cpuset))


def get_number_of_serial_ports(flavor, image_meta):
    """Get the number of serial consoles from the flavor or image

    :param flavor: Flavor object to read extra specs from
    :param image_meta: Image object to read image metadata from

    If flavor extra specs is not set, then any image meta value is permitted.
    If flavour extra specs *is* set, then this provides the default serial
    port count. The image meta is permitted to override the extra specs, but
    *only* with a lower value. ie

    - flavor hw:serial_port_count=4
      VM gets 4 serial ports
    - flavor hw:serial_port_count=4 and image hw_serial_port_count=2
      VM gets 2 serial ports
    - image hw_serial_port_count=6
      VM gets 6 serial ports
    - flavor hw:serial_port_count=4 and image hw_serial_port_count=6
      Abort guest boot - forbidden to exceed flavor value

    :returns: number of serial ports
    """

    def get_number(obj, property):
        num_ports = obj.get(property)
        if num_ports is not None:
            try:
                num_ports = int(num_ports)
            except ValueError:
                raise exception.ImageSerialPortNumberInvalid(
                    num_ports=num_ports, property=property)
        return num_ports

    image_meta_prop = (image_meta or {}).get('properties', {})

    flavor_num_ports = get_number(flavor.extra_specs, "hw:serial_port_count")
    image_num_ports = get_number(image_meta_prop, "hw_serial_port_count")

    if (flavor_num_ports and image_num_ports) is not None:
        if image_num_ports > flavor_num_ports:
            raise exception.ImageSerialPortNumberExceedFlavorValue()
        return image_num_ports

    return flavor_num_ports or image_num_ports or 1


class InstanceInfo(object):

    def __init__(self, state=None, max_mem_kb=0, mem_kb=0, num_cpu=0,
                 cpu_time_ns=0, id=None):
        """Create a new Instance Info object

        :param state: the running state, one of the power_state codes
        :param max_mem_kb: (int) the maximum memory in KBytes allowed
        :param mem_kb: (int) the memory in KBytes used by the instance
        :param num_cpu: (int) the number of virtual CPUs for the instance
        :param cpu_time_ns: (int) the CPU time used in nanoseconds
        :param id: a unique ID for the instance
        """
        self.state = state
        self.max_mem_kb = max_mem_kb
        self.mem_kb = mem_kb
        self.num_cpu = num_cpu
        self.cpu_time_ns = cpu_time_ns
        self.id = id

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.__dict__ == other.__dict__)


def _score_cpu_topology(topology, wanttopology):
    """Calculate score for the topology against a desired configuration

    :param wanttopology: nova.objects.VirtCPUTopology instance for
                         preferred topology

    Calculate a score indicating how well this topology
    matches against a preferred topology. A score of 3
    indicates an exact match for sockets, cores and threads.
    A score of 2 indicates a match of sockets & cores or
    sockets & threads or cores and threads. A score of 1
    indicates a match of sockets or cores or threads. A
    score of 0 indicates no match

    :returns: score in range 0 (worst) to 3 (best)
    """

    score = 0
    if (wanttopology.sockets != -1 and
        topology.sockets == wanttopology.sockets):
        score = score + 1
    if (wanttopology.cores != -1 and
        topology.cores == wanttopology.cores):
        score = score + 1
    if (wanttopology.threads != -1 and
        topology.threads == wanttopology.threads):
        score = score + 1
    return score


def _get_cpu_topology_constraints(flavor, image_meta):
    """Get the topology constraints declared in flavor or image

    :param flavor: Flavor object to read extra specs from
    :param image_meta: Image object to read image metadata from

    Gets the topology constraints from the configuration defined
    in the flavor extra specs or the image metadata. In the flavor
    this will look for

     hw:cpu_sockets - preferred socket count
     hw:cpu_cores - preferred core count
     hw:cpu_threads - preferred thread count
     hw:cpu_maxsockets - maximum socket count
     hw:cpu_maxcores - maximum core count
     hw:cpu_maxthreads - maximum thread count

    In the image metadata this will look at

     hw_cpu_sockets - preferred socket count
     hw_cpu_cores - preferred core count
     hw_cpu_threads - preferred thread count
     hw_cpu_maxsockets - maximum socket count
     hw_cpu_maxcores - maximum core count
     hw_cpu_maxthreads - maximum thread count

    The image metadata must be strictly lower than any values
    set in the flavor. All values are, however, optional.

    This will return a pair of nova.objects.VirtCPUTopology instances,
    the first giving the preferred socket/core/thread counts,
    and the second giving the upper limits on socket/core/
    thread counts.

    exception.ImageVCPULimitsRangeExceeded will be raised
    if the maximum counts set against the image exceed
    the maximum counts set against the flavor

    exception.ImageVCPUTopologyRangeExceeded will be raised
    if the preferred counts set against the image exceed
    the maximum counts set against the image or flavor

    :returns: (preferred topology, maximum topology)
    """

    # Obtain the absolute limits from the flavor
    flvmaxsockets = int(flavor.extra_specs.get(
        "hw:cpu_max_sockets", 65536))
    flvmaxcores = int(flavor.extra_specs.get(
        "hw:cpu_max_cores", 65536))
    flvmaxthreads = int(flavor.extra_specs.get(
        "hw:cpu_max_threads", 65536))

    LOG.debug("Flavor limits %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": flvmaxsockets,
               "cores": flvmaxcores,
               "threads": flvmaxthreads})

    # Get any customized limits from the image
    maxsockets = int(image_meta.get("properties", {})
                     .get("hw_cpu_max_sockets", flvmaxsockets))
    maxcores = int(image_meta.get("properties", {})
                   .get("hw_cpu_max_cores", flvmaxcores))
    maxthreads = int(image_meta.get("properties", {})
                     .get("hw_cpu_max_threads", flvmaxthreads))

    LOG.debug("Image limits %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": maxsockets,
               "cores": maxcores,
               "threads": maxthreads})

    # Image limits are not permitted to exceed the flavor
    # limits. ie they can only lower what the flavor defines
    if ((maxsockets > flvmaxsockets) or
        (maxcores > flvmaxcores) or
        (maxthreads > flvmaxthreads)):
        raise exception.ImageVCPULimitsRangeExceeded(
            sockets=maxsockets,
            cores=maxcores,
            threads=maxthreads,
            maxsockets=flvmaxsockets,
            maxcores=flvmaxcores,
            maxthreads=flvmaxthreads)

    # Get any default preferred topology from the flavor
    flvsockets = int(flavor.extra_specs.get("hw:cpu_sockets", -1))
    flvcores = int(flavor.extra_specs.get("hw:cpu_cores", -1))
    flvthreads = int(flavor.extra_specs.get("hw:cpu_threads", -1))

    LOG.debug("Flavor pref %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": flvsockets,
               "cores": flvcores,
               "threads": flvthreads})

    # If the image limits have reduced the flavor limits
    # we might need to discard the preferred topology
    # from the flavor
    if ((flvsockets > maxsockets) or
        (flvcores > maxcores) or
        (flvthreads > maxthreads)):
        flvsockets = flvcores = flvthreads = -1

    # Finally see if the image has provided a preferred
    # topology to use
    sockets = int(image_meta.get("properties", {})
                  .get("hw_cpu_sockets", -1))
    cores = int(image_meta.get("properties", {})
                .get("hw_cpu_cores", -1))
    threads = int(image_meta.get("properties", {})
                  .get("hw_cpu_threads", -1))

    LOG.debug("Image pref %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": sockets,
               "cores": cores,
               "threads": threads})

    # Image topology is not permitted to exceed image/flavor
    # limits
    if ((sockets > maxsockets) or
        (cores > maxcores) or
        (threads > maxthreads)):
        raise exception.ImageVCPUTopologyRangeExceeded(
            sockets=sockets,
            cores=cores,
            threads=threads,
            maxsockets=maxsockets,
            maxcores=maxcores,
            maxthreads=maxthreads)

    # If no preferred topology was set against the image
    # then use the preferred topology from the flavor
    # We use 'and' not 'or', since if any value is set
    # against the image this invalidates the entire set
    # of values from the flavor
    if sockets == -1 and cores == -1 and threads == -1:
        sockets = flvsockets
        cores = flvcores
        threads = flvthreads

    LOG.debug("Chosen %(sockets)d:%(cores)d:%(threads)d limits "
              "%(maxsockets)d:%(maxcores)d:%(maxthreads)d",
              {"sockets": sockets, "cores": cores,
               "threads": threads, "maxsockets": maxsockets,
               "maxcores": maxcores, "maxthreads": maxthreads})

    return (objects.VirtCPUTopology(sockets=sockets, cores=cores,
                                    threads=threads),
            objects.VirtCPUTopology(sockets=maxsockets, cores=maxcores,
                                    threads=maxthreads))


def _get_possible_cpu_topologies(vcpus, maxtopology, allow_threads):
    """Get a list of possible topologies for a vCPU count
    :param vcpus: total number of CPUs for guest instance
    :param maxtopology: nova.objects.VirtCPUTopology for upper limits
    :param allow_threads: if the hypervisor supports CPU threads

    Given a total desired vCPU count and constraints on the
    maximum number of sockets, cores and threads, return a
    list of nova.objects.VirtCPUTopology instances that represent every
    possible topology that satisfies the constraints.

    exception.ImageVCPULimitsRangeImpossible is raised if
    it is impossible to achieve the total vcpu count given
    the maximum limits on sockets, cores & threads.

    :returns: list of nova.objects.VirtCPUTopology instances
    """

    # Clamp limits to number of vcpus to prevent
    # iterating over insanely large list
    maxsockets = min(vcpus, maxtopology.sockets)
    maxcores = min(vcpus, maxtopology.cores)
    maxthreads = min(vcpus, maxtopology.threads)

    if not allow_threads:
        maxthreads = 1

    LOG.debug("Build topologies for %(vcpus)d vcpu(s) "
              "%(maxsockets)d:%(maxcores)d:%(maxthreads)d",
              {"vcpus": vcpus, "maxsockets": maxsockets,
               "maxcores": maxcores, "maxthreads": maxthreads})

    # Figure out all possible topologies that match
    # the required vcpus count and satisfy the declared
    # limits. If the total vCPU count were very high
    # it might be more efficient to factorize the vcpu
    # count and then only iterate over its factors, but
    # that's overkill right now
    possible = []
    for s in range(1, maxsockets + 1):
        for c in range(1, maxcores + 1):
            for t in range(1, maxthreads + 1):
                if t * c * s == vcpus:
                    o = objects.VirtCPUTopology(sockets=s, cores=c,
                                                threads=t)

                    possible.append(o)

    # We want to
    #  - Minimize threads (ie larger sockets * cores is best)
    #  - Prefer sockets over cores
    possible = sorted(possible, reverse=True,
                      key=lambda x: (x.sockets * x.cores,
                                     x.sockets,
                                     x.threads))

    LOG.debug("Got %d possible topologies", len(possible))
    if len(possible) == 0:
        raise exception.ImageVCPULimitsRangeImpossible(vcpus=vcpus,
                                                       sockets=maxsockets,
                                                       cores=maxcores,
                                                       threads=maxthreads)

    return possible


def _sort_possible_cpu_topologies(possible, wanttopology):
    """Sort the topologies in order of preference
    :param possible: list of nova.objects.VirtCPUTopology instances
    :param wanttopology: nova.objects.VirtCPUTopology for preferred
                         topology

    This takes the list of possible topologies and resorts
    it such that those configurations which most closely
    match the preferred topology are first.

    :returns: sorted list of nova.objects.VirtCPUTopology instances
    """

    # Look at possible topologies and score them according
    # to how well they match the preferred topologies
    # We don't use python's sort(), since we want to
    # preserve the sorting done when populating the
    # 'possible' list originally
    scores = collections.defaultdict(list)
    for topology in possible:
        score = _score_cpu_topology(topology, wanttopology)
        scores[score].append(topology)

    # Build list of all possible topologies sorted
    # by the match score, best match first
    desired = []
    desired.extend(scores[3])
    desired.extend(scores[2])
    desired.extend(scores[1])
    desired.extend(scores[0])

    return desired


def _get_desirable_cpu_topologies(flavor, image_meta, allow_threads=True):
    """Get desired CPU topologies according to settings

    :param flavor: Flavor object to query extra specs from
    :param image_meta: ImageMeta object to query properties from
    :param allow_threads: if the hypervisor supports CPU threads

    Look at the properties set in the flavor extra specs and
    the image metadata and build up a list of all possible
    valid CPU topologies that can be used in the guest. Then
    return this list sorted in order of preference.

    :returns: sorted list of nova.objects.VirtCPUTopology instances
    """

    LOG.debug("Getting desirable topologies for flavor %(flavor)s "
              "and image_meta %(image_meta)s",
              {"flavor": flavor, "image_meta": image_meta})

    preferred, maximum = _get_cpu_topology_constraints(flavor, image_meta)

    possible = _get_possible_cpu_topologies(flavor.vcpus,
                                            maximum,
                                            allow_threads)
    desired = _sort_possible_cpu_topologies(possible, preferred)

    return desired


def get_best_cpu_topology(flavor, image_meta, allow_threads=True):
    """Get best CPU topology according to settings

    :param flavor: Flavor object to query extra specs from
    :param image_meta: ImageMeta object to query properties from
    :param allow_threads: if the hypervisor supports CPU threads

    Look at the properties set in the flavor extra specs and
    the image metadata and build up a list of all possible
    valid CPU topologies that can be used in the guest. Then
    return the best topology to use

    :returns: a nova.objects.VirtCPUTopology instance for best topology
    """

    return _get_desirable_cpu_topologies(flavor, image_meta, allow_threads)[0]


class VirtNUMATopologyCell(object):
    """Class for reporting NUMA resources in a cell

    The VirtNUMATopologyCell class represents the
    hardware resources present in a NUMA cell.
    """

    def __init__(self, id, cpuset, memory):
        """Create a new NUMA Cell

        :param id: integer identifier of cell
        :param cpuset: set containing list of CPU indexes
        :param memory: RAM measured in MiB

        Creates a new NUMA cell object to record the hardware
        resources.

        :returns: a new NUMA cell object
        """

        super(VirtNUMATopologyCell, self).__init__()

        self.id = id
        self.cpuset = cpuset
        self.memory = memory

    def _to_dict(self):
        return {'cpus': format_cpu_spec(self.cpuset, allow_ranges=False),
                'mem': {'total': self.memory},
                'id': self.id}

    @classmethod
    def _from_dict(cls, data_dict):
        cpuset = parse_cpu_spec(data_dict.get('cpus', ''))
        memory = data_dict.get('mem', {}).get('total', 0)
        cell_id = data_dict.get('id')
        return cls(cell_id, cpuset, memory)


class VirtNUMATopologyCellLimit(VirtNUMATopologyCell):
    def __init__(self, id, cpuset, memory, cpu_limit, memory_limit):
        """Create a new NUMA Cell with usage

        :param id: integer identifier of cell
        :param cpuset: set containing list of CPU indexes
        :param memory: RAM measured in MiB
        :param cpu_limit: maximum number of  CPUs allocated
        :param memory_usage: maxumum RAM allocated in MiB

        Creates a new NUMA cell object to represent the max hardware
        resources and utilization. The number of CPUs specified
        by the @cpu_usage parameter may be larger than the number
        of bits set in @cpuset if CPU overcommit is used. Likewise
        the amount of RAM specified by the @memory_usage parameter
        may be larger than the available RAM in @memory if RAM
        overcommit is used.

        :returns: a new NUMA cell object
        """

        super(VirtNUMATopologyCellLimit, self).__init__(
            id, cpuset, memory)

        self.cpu_limit = cpu_limit
        self.memory_limit = memory_limit

    def _to_dict(self):
        data_dict = super(VirtNUMATopologyCellLimit, self)._to_dict()
        data_dict['mem']['limit'] = self.memory_limit
        data_dict['cpu_limit'] = self.cpu_limit
        return data_dict

    @classmethod
    def _from_dict(cls, data_dict):
        cpuset = parse_cpu_spec(data_dict.get('cpus', ''))
        memory = data_dict.get('mem', {}).get('total', 0)
        cpu_limit = data_dict.get('cpu_limit', len(cpuset))
        memory_limit = data_dict.get('mem', {}).get('limit', memory)
        cell_id = data_dict.get('id')
        return cls(cell_id, cpuset, memory, cpu_limit, memory_limit)


def _numa_cell_supports_pagesize_request(host_cell, inst_cell):
    """Determines whether the cell can accept the request.

    :param host_cell: host cell to fit the instance cell onto
    :param inst_cell: instance cell we want to fit

    :returns: The page size able to be handled by host_cell
    """
    avail_pagesize = [page.size_kb for page in host_cell.mempages]
    avail_pagesize.sort(reverse=True)

    def verify_pagesizes(host_cell, inst_cell, avail_pagesize):
        inst_cell_mem = inst_cell.memory * units.Ki
        for pagesize in avail_pagesize:
            if host_cell.can_fit_hugepages(pagesize, inst_cell_mem):
                return pagesize

    if inst_cell.pagesize == MEMPAGES_SMALL:
        return verify_pagesizes(host_cell, inst_cell, avail_pagesize[-1:])
    elif inst_cell.pagesize == MEMPAGES_LARGE:
        return verify_pagesizes(host_cell, inst_cell, avail_pagesize[:-1])
    elif inst_cell.pagesize == MEMPAGES_ANY:
        return verify_pagesizes(host_cell, inst_cell, avail_pagesize)
    else:
        return verify_pagesizes(host_cell, inst_cell, [inst_cell.pagesize])


def _pack_instance_onto_cores(available_siblings, instance_cell, host_cell_id):
    """Pack an instance onto a set of siblings

    :param available_siblings: list of sets of CPU id's - available
                               siblings per core
    :param instance_cell: An instance of objects.InstanceNUMACell describing
                          the pinning requirements of the instance

    :returns: An instance of objects.InstanceNUMACell containing the pinning
              information, and potentially a new topology to be exposed to the
              instance. None if there is no valid way to satisfy the sibling
              requirements for the instance.

    This method will calculate the pinning for the given instance and it's
    topology, making sure that hyperthreads of the instance match up with
    those of the host when the pinning takes effect.
    """

    # We build up a data structure 'can_pack' that answers the question:
    # 'Given the number of threads I want to pack, give me a list of all
    # the available sibling sets that can accomodate it'
    can_pack = collections.defaultdict(list)
    for sib in available_siblings:
        for threads_no in range(1, len(sib) + 1):
            can_pack[threads_no].append(sib)

    def _can_pack_instance_cell(instance_cell, threads_per_core, cores_list):
        """Determines if instance cell can fit an avail set of cores."""

        if threads_per_core * len(cores_list) < len(instance_cell):
            return False
        if instance_cell.siblings:
            return instance_cell.cpu_topology.threads <= threads_per_core
        else:
            return len(instance_cell) % threads_per_core == 0

    # We iterate over the can_pack dict in descending order of cores that
    # can be packed - an attempt to get even distribution over time
    for cores_per_sib, sib_list in sorted(
            (t for t in can_pack.items()), reverse=True):
        if _can_pack_instance_cell(instance_cell,
                                   cores_per_sib, sib_list):
            sliced_sibs = map(lambda s: list(s)[:cores_per_sib], sib_list)
            if instance_cell.siblings:
                pinning = zip(itertools.chain(*instance_cell.siblings),
                              itertools.chain(*sliced_sibs))
            else:
                pinning = zip(sorted(instance_cell.cpuset),
                              itertools.chain(*sliced_sibs))

            topology = (instance_cell.cpu_topology or
                        objects.VirtCPUTopology(sockets=1,
                                                cores=len(sliced_sibs),
                                                threads=cores_per_sib))
            instance_cell.pin_vcpus(*pinning)
            instance_cell.cpu_topology = topology
            instance_cell.id = host_cell_id
            return instance_cell


def _numa_fit_instance_cell_with_pinning(host_cell, instance_cell):
    """Figure out if cells can be pinned to a host cell and return details

    :param host_cell: objects.NUMACell instance - the host cell that
                      the isntance should be pinned to
    :param instance_cell: objects.InstanceNUMACell instance without any
                          pinning information

    :returns: objects.InstanceNUMACell instance with pinning information,
              or None if instance cannot be pinned to the given host
    """
    if (host_cell.avail_cpus < len(instance_cell.cpuset) or
        host_cell.avail_memory < instance_cell.memory):
        # If we do not have enough CPUs available or not enough memory
        # on the host cell, we quit early (no oversubscription).
        return

    if host_cell.siblings:
        # Instance requires hyperthreading in it's topology
        if instance_cell.cpu_topology and instance_cell.siblings:
            return _pack_instance_onto_cores(host_cell.free_siblings,
                                             instance_cell, host_cell.id)

        else:
            # Try to pack the instance cell in one core
            largest_free_sibling_set = sorted(
                host_cell.free_siblings, key=len)[-1]
            if (len(instance_cell.cpuset) <=
                    len(largest_free_sibling_set)):
                return _pack_instance_onto_cores(
                    [largest_free_sibling_set], instance_cell, host_cell.id)

            # We can't to pack it onto one core so try with avail siblings
            else:
                return _pack_instance_onto_cores(
                    host_cell.free_siblings, instance_cell, host_cell.id)
    else:
        # Straightforward to pin to available cpus when there is no
        # hyperthreading on the host
        return _pack_instance_onto_cores(
            [host_cell.free_cpus], instance_cell, host_cell.id)


def _numa_fit_instance_cell(host_cell, instance_cell, limit_cell=None):
    """Check if a instance cell can fit and set it's cell id

    :param host_cell: host cell to fit the instance cell onto
    :param instance_cell: instance cell we want to fit
    :param limit_cell: cell with limits of the host_cell if any

    Make sure we can fit the instance cell onto a host cell and if so,
    return a new objects.InstanceNUMACell with the id set to that of
    the host, or None if the cell exceeds the limits of the host

    :returns: a new instance cell or None
    """
    # NOTE (ndipanov): do not allow an instance to overcommit against
    # itself on any NUMA cell
    if (instance_cell.memory > host_cell.memory or
            len(instance_cell.cpuset) > len(host_cell.cpuset)):
        return None

    if instance_cell.cpu_pinning is not None:
        new_instance_cell = _numa_fit_instance_cell_with_pinning(
            host_cell, instance_cell)
        if not new_instance_cell:
            return
        new_instance_cell.pagesize = instance_cell.pagesize
        instance_cell = new_instance_cell

    elif limit_cell:
        memory_usage = host_cell.memory_usage + instance_cell.memory
        cpu_usage = host_cell.cpu_usage + len(instance_cell.cpuset)
        if (memory_usage > limit_cell.memory_limit or
                cpu_usage > limit_cell.cpu_limit):
            return None

    pagesize = None
    if instance_cell.pagesize:
        pagesize = _numa_cell_supports_pagesize_request(
            host_cell, instance_cell)
        if not pagesize:
            return

    instance_cell.id = host_cell.id
    instance_cell.pagesize = pagesize
    return instance_cell


class VirtNUMATopology(object):
    """Base class for tracking NUMA topology information

    The VirtNUMATopology class represents the NUMA hardware
    topology for memory and CPUs in any machine. It is
    later specialized for handling either guest instance
    or compute host NUMA topology.
    """

    def __init__(self, cells=None):
        """Create a new NUMA topology object

        :param cells: list of VirtNUMATopologyCell instances

        """

        super(VirtNUMATopology, self).__init__()

        self.cells = cells or []

    def __len__(self):
        """Defined so that boolean testing works the same as for lists."""
        return len(self.cells)

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, str(self._to_dict()))

    def _to_dict(self):
        return {'cells': [cell._to_dict() for cell in self.cells]}

    @classmethod
    def _from_dict(cls, data_dict):
        return cls(cells=[cls.cell_class._from_dict(cell_dict)
                          for cell_dict in data_dict.get('cells', [])])

    def to_json(self):
        return jsonutils.dumps(self._to_dict())

    @classmethod
    def from_json(cls, json_string):
        return cls._from_dict(jsonutils.loads(json_string))


def _numa_get_flavor_or_image_prop(flavor, image_meta, propname):
    """Return the value of propname from flavor or image

    :param flavor: a Flavor object or dict of instance type information
    :param image_meta: a dict of image information

    :returns: a value or None
    """
    flavor_val = flavor.get('extra_specs', {}).get("hw:" + propname)
    image_val = (image_meta or {}).get("properties", {}).get("hw_" + propname)

    if flavor_val is not None:
        if image_val is not None:
            raise exception.ImageNUMATopologyForbidden(
                name='hw_' + propname)

        return flavor_val
    else:
        return image_val


def _numa_get_pagesize_constraints(flavor, image_meta):
    """Return the requested memory page size

    :param flavor: a Flavor object to read extra specs from
    :param image_meta: an Image object to read meta data from

    :raises: MemoryPagesSizeInvalid or MemoryPageSizeForbidden
    :returns: a page size requested or MEMPAGES_*
    """

    def check_and_return_pages_size(request):
        if request == "any":
            return MEMPAGES_ANY
        elif request == "large":
            return MEMPAGES_LARGE
        elif request == "small":
            return MEMPAGES_SMALL
        else:
            try:
                request = int(request)
            except ValueError:
                request = 0

        if request <= 0:
            raise exception.MemoryPageSizeInvalid(pagesize=request)

        return request

    image_meta_prop = (image_meta or {}).get("properties", {})

    flavor_request = flavor.get('extra_specs', {}).get("hw:mem_page_size", "")
    image_request = image_meta_prop.get("hw_mem_page_size", "")

    if not flavor_request and image_request:
        raise exception.MemoryPageSizeForbidden(
            pagesize=image_request,
            against="<empty>")

    if not flavor_request:
        # Nothing was specified for hugepages,
        # let's the default process running.
        return None

    pagesize = check_and_return_pages_size(flavor_request)
    if image_request and (pagesize in (MEMPAGES_ANY, MEMPAGES_LARGE)):
        return check_and_return_pages_size(image_request)
    elif image_request:
        raise exception.MemoryPageSizeForbidden(
            pagesize=image_request,
            against=flavor_request)

    return pagesize


def _numa_get_constraints_manual(nodes, flavor, image_meta):
    cells = []
    totalmem = 0

    availcpus = set(range(flavor['vcpus']))

    for node in range(nodes):
        cpus = _numa_get_flavor_or_image_prop(
            flavor, image_meta, "numa_cpus.%d" % node)
        mem = _numa_get_flavor_or_image_prop(
            flavor, image_meta, "numa_mem.%d" % node)

        # We're expecting both properties set, so
        # raise an error if either is missing
        if cpus is None or mem is None:
            raise exception.ImageNUMATopologyIncomplete()

        mem = int(mem)
        cpuset = parse_cpu_spec(cpus)

        for cpu in cpuset:
            if cpu > (flavor['vcpus'] - 1):
                raise exception.ImageNUMATopologyCPUOutOfRange(
                    cpunum=cpu, cpumax=(flavor['vcpus'] - 1))

            if cpu not in availcpus:
                raise exception.ImageNUMATopologyCPUDuplicates(
                    cpunum=cpu)

            availcpus.remove(cpu)

        cells.append(objects.InstanceNUMACell(
            id=node, cpuset=cpuset, memory=mem))
        totalmem = totalmem + mem

    if availcpus:
        raise exception.ImageNUMATopologyCPUsUnassigned(
            cpuset=str(availcpus))

    if totalmem != flavor['memory_mb']:
        raise exception.ImageNUMATopologyMemoryOutOfRange(
            memsize=totalmem,
            memtotal=flavor['memory_mb'])

    return objects.InstanceNUMATopology(cells=cells)


def _numa_get_constraints_auto(nodes, flavor, image_meta):
    if ((flavor['vcpus'] % nodes) > 0 or
        (flavor['memory_mb'] % nodes) > 0):
        raise exception.ImageNUMATopologyAsymmetric()

    cells = []
    for node in range(nodes):
        cpus = _numa_get_flavor_or_image_prop(
            flavor, image_meta, "numa_cpus.%d" % node)
        mem = _numa_get_flavor_or_image_prop(
            flavor, image_meta, "numa_mem.%d" % node)

        # We're not expecting any properties set, so
        # raise an error if there are any
        if cpus is not None or mem is not None:
            raise exception.ImageNUMATopologyIncomplete()

        ncpus = int(flavor['vcpus'] / nodes)
        mem = int(flavor['memory_mb'] / nodes)
        start = node * ncpus
        cpuset = set(range(start, start + ncpus))

        cells.append(objects.InstanceNUMACell(
            id=node, cpuset=cpuset, memory=mem))

    return objects.InstanceNUMATopology(cells=cells)


# TODO(sahid): Move numa related to hardward/numa.py
def numa_get_constraints(flavor, image_meta):
    """Return topology related to input request

    :param flavor: Flavor object to read extra specs from
    :param image_meta: Image object to read image metadata from

    :returns: InstanceNUMATopology or None
    """
    nodes = _numa_get_flavor_or_image_prop(
        flavor, image_meta, "numa_nodes")
    pagesize = _numa_get_pagesize_constraints(
        flavor, image_meta)

    topology = None
    if nodes or pagesize:
        nodes = nodes and int(nodes) or 1
        # We'll pick what path to go down based on whether
        # anything is set for the first node. Both paths
        # have logic to cope with inconsistent property usage
        auto = _numa_get_flavor_or_image_prop(
            flavor, image_meta, "numa_cpus.0") is None

        if auto:
            topology = _numa_get_constraints_auto(
                nodes, flavor, image_meta)
        else:
            topology = _numa_get_constraints_manual(
                nodes, flavor, image_meta)

        # We currently support same pagesize for all cells.
        [setattr(c, 'pagesize', pagesize) for c in topology.cells]

    return topology


class VirtNUMALimitTopology(VirtNUMATopology):
    """Class to represent the max resources of a compute node used
    for checking oversubscription limits.
    """

    cell_class = VirtNUMATopologyCellLimit


def numa_fit_instance_to_host(
        host_topology, instance_topology, limits_topology=None):
    """Fit the instance topology onto the host topology given the limits

    :param host_topology: objects.NUMATopology object to fit an instance on
    :param instance_topology: objects.InstanceNUMATopology to be fitted
    :param limits_topology: VirtNUMALimitTopology that defines limits

    Given a host and instance topology and optionally limits - this method
    will attempt to fit instance cells onto all permutations of host cells
    by calling the _numa_fit_instance_cell method, and return a new
    InstanceNUMATopology with it's cell ids set to host cell id's of
    the first successful permutation, or None.
    """
    if (not (host_topology and instance_topology) or
        len(host_topology) < len(instance_topology)):
        return
    else:
        if limits_topology is None:
            limits_topology_cells = itertools.repeat(
                None, len(host_topology))
        else:
            limits_topology_cells = limits_topology.cells
        # TODO(ndipanov): We may want to sort permutations differently
        # depending on whether we want packing/spreading over NUMA nodes
        for host_cell_perm in itertools.permutations(
                zip(host_topology.cells, limits_topology_cells),
                len(instance_topology)
        ):
            cells = []
            for (host_cell, limit_cell), instance_cell in zip(
                    host_cell_perm, instance_topology.cells):
                got_cell = _numa_fit_instance_cell(
                    host_cell, instance_cell, limit_cell)
                if got_cell is None:
                    break
                cells.append(got_cell)
            if len(cells) == len(host_cell_perm):
                return objects.InstanceNUMATopology(cells=cells)


def _numa_pagesize_usage_from_cell(hostcell, instancecell, sign):
    topo = []
    for pages in hostcell.mempages:
        if pages.size_kb == instancecell.pagesize:
            topo.append(objects.NUMAPagesTopology(
                size_kb=pages.size_kb,
                total=pages.total,
                used=max(0, pages.used +
                         instancecell.memory * units.Ki /
                         pages.size_kb * sign)))
        else:
            topo.append(pages)
    return topo


def numa_usage_from_instances(host, instances, free=False):
    """Get host topology usage

    :param host: objects.NUMATopology with usage information
    :param instances: list of objects.InstanceNUMATopology
    :param free: If True usage of the host will be decreased

    Sum the usage from all @instances to report the overall
    host topology usage

    :returns: objects.NUMATopology including usage information
    """

    if host is None:
        return

    instances = instances or []
    cells = []
    sign = -1 if free else 1
    for hostcell in host.cells:
        memory_usage = hostcell.memory_usage
        cpu_usage = hostcell.cpu_usage
        mempages = hostcell.mempages
        for instance in instances:
            for instancecell in instance.cells:
                if instancecell.id == hostcell.id:
                    memory_usage = (
                            memory_usage + sign * instancecell.memory)
                    cpu_usage = cpu_usage + sign * len(instancecell.cpuset)
                    if instancecell.pagesize and instancecell.pagesize > 0:
                        mempages = _numa_pagesize_usage_from_cell(
                            hostcell, instancecell, sign)

        cell = objects.NUMACell(
            id=hostcell.id, cpuset=hostcell.cpuset, memory=hostcell.memory,
            cpu_usage=max(0, cpu_usage), memory_usage=max(0, memory_usage),
            mempages=mempages)

        cells.append(cell)

    return objects.NUMATopology(cells=cells)


# TODO(ndipanov): Remove when all code paths are using objects
def instance_topology_from_instance(instance):
    """Convenience method for getting the numa_topology out of instances

    Since we may get an Instance as either a dict, a db object, or an actual
    Instance object, this makes sure we get beck either None, or an instance
    of objects.InstanceNUMATopology class.
    """
    if isinstance(instance, objects.Instance):
        # NOTE (ndipanov): This may cause a lazy-load of the attribute
        instance_numa_topology = instance.numa_topology
    else:
        if 'numa_topology' in instance:
            instance_numa_topology = instance['numa_topology']
        elif 'uuid' in instance:
            try:
                instance_numa_topology = (
                    objects.InstanceNUMATopology.get_by_instance_uuid(
                            context.get_admin_context(), instance['uuid'])
                    )
            except exception.NumaTopologyNotFound:
                instance_numa_topology = None
        else:
            instance_numa_topology = None

    if instance_numa_topology:
        if isinstance(instance_numa_topology, six.string_types):
            instance_numa_topology = (
                objects.InstanceNUMATopology.obj_from_primitive(
                    jsonutils.loads(instance_numa_topology)))

        elif isinstance(instance_numa_topology, dict):
            # NOTE (ndipanov): A horrible hack so that we can use
            # this in the scheduler, since the
            # InstanceNUMATopology object is serialized raw using
            # the obj_base.obj_to_primitive, (which is buggy and
            # will give us a dict with a list of InstanceNUMACell
            # objects), and then passed to jsonutils.to_primitive,
            # which will make a dict out of those objects. All of
            # this is done by scheduler.utils.build_request_spec
            # called in the conductor.
            #
            # Remove when request_spec is a proper object itself!
            dict_cells = instance_numa_topology.get('cells')
            if dict_cells:
                cells = [objects.InstanceNUMACell(
                    id=cell['id'],
                    cpuset=set(cell['cpuset']),
                    memory=cell['memory'],
                    pagesize=cell.get('pagesize'))
                         for cell in dict_cells]
                instance_numa_topology = objects.InstanceNUMATopology(
                    cells=cells)

    return instance_numa_topology


# TODO(ndipanov): Remove when all code paths are using objects
def host_topology_and_format_from_host(host):
    """Convenience method for getting the numa_topology out of hosts

    Since we may get a host as either a dict, a db object, or an actual
    ComputeNode object, or an instance of HostState class, this makes sure we
    get beck either None, or an instance of objects.NUMATopology class.

    :returns: A two-tuple, first element is the topology itself or None, second
              is a boolean set to True if topology was in json format.
    """
    was_json = False
    try:
        host_numa_topology = host.get('numa_topology')
    except AttributeError:
        host_numa_topology = host.numa_topology

    if host_numa_topology is not None and isinstance(
            host_numa_topology, six.string_types):
        was_json = True

        host_numa_topology = (objects.NUMATopology.obj_from_db_obj(
            host_numa_topology))

    return host_numa_topology, was_json


# TODO(ndipanov): Remove when all code paths are using objects
def get_host_numa_usage_from_instance(host, instance, free=False,
                                     never_serialize_result=False):
    """Calculate new 'numa_usage' of 'host' from 'instance' NUMA usage

    This is a convenience method to help us handle the fact that we use several
    different types throughout the code (ComputeNode and Instance objects,
    dicts, scheduler HostState) which may have both json and deserialized
    versions of VirtNUMATopology classes.

    Handles all the complexity without polluting the class method with it.

    :param host: nova.objects.ComputeNode instance, or a db object or dict
    :param instance: nova.objects.Instance instance, or a db object or dict
    :param free: if True the the returned topology will have it's usage
                 decreased instead.
    :param never_serialize_result: if True result will always be an instance of
                                   objects.NUMATopology class.

    :returns: numa_usage in the format it was on the host or
              objects.NUMATopology instance if never_serialize_result was True
    """
    instance_numa_topology = instance_topology_from_instance(instance)
    if instance_numa_topology:
        instance_numa_topology = [instance_numa_topology]

    host_numa_topology, jsonify_result = host_topology_and_format_from_host(
            host)

    updated_numa_topology = (
        numa_usage_from_instances(
            host_numa_topology, instance_numa_topology, free=free))

    if updated_numa_topology is not None:
        if jsonify_result and not never_serialize_result:
            updated_numa_topology = updated_numa_topology._to_json()

    return updated_numa_topology
