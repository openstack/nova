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
import fractions
import itertools

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import strutils
from oslo_utils import units
import six

import nova.conf
from nova import context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import fields
from nova.objects import instance as obj_instance


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

MEMPAGES_SMALL = -1
MEMPAGES_LARGE = -2
MEMPAGES_ANY = -3


def get_vcpu_pin_set():
    """Parse vcpu_pin_set config.

    :returns: a set of pcpu ids can be used by instances
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

    Each element in the list is either a single CPU number, a range of
    CPU numbers, or a caret followed by a CPU number to be excluded
    from a previous range.

    :param spec: cpu set string eg "1-4,^3,6"

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
            reject = False
            if range_parts[0] and range_parts[0][0] == '^':
                reject = True
                range_parts[0] = str(range_parts[0][1:])

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
            if not reject:
                cpuset_ids |= set(range(start, end + 1))
            else:
                cpuset_reject_ids |= set(range(start, end + 1))
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

    Format a set/list of CPU indexes as a libvirt CPU range
    specification. If allow_ranges is true, it will try to detect
    continuous ranges of CPUs, otherwise it will just list each CPU
    index explicitly.

    :param cpuset: set (or list) of CPU indexes

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
    """Get the number of serial consoles from the flavor or image.

    If flavor extra specs is not set, then any image meta value is
    permitted.  If flavor extra specs *is* set, then this provides the
    default serial port count. The image meta is permitted to override
    the extra specs, but *only* with a lower value, i.e.:

    - flavor hw:serial_port_count=4
      VM gets 4 serial ports
    - flavor hw:serial_port_count=4 and image hw_serial_port_count=2
      VM gets 2 serial ports
    - image hw_serial_port_count=6
      VM gets 6 serial ports
    - flavor hw:serial_port_count=4 and image hw_serial_port_count=6
      Abort guest boot - forbidden to exceed flavor value

    :param flavor: Flavor object to read extra specs from
    :param image_meta: nova.objects.ImageMeta object instance

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

    flavor_num_ports = get_number(flavor.extra_specs, "hw:serial_port_count")
    image_num_ports = image_meta.properties.get("hw_serial_port_count", None)

    if (flavor_num_ports and image_num_ports) is not None:
        if image_num_ports > flavor_num_ports:
            raise exception.ImageSerialPortNumberExceedFlavorValue()
        return image_num_ports

    return flavor_num_ports or image_num_ports or 1


class InstanceInfo(object):

    def __init__(self, state, internal_id=None):
        """Create a new Instance Info object

        :param state: Required. The running state, one of the power_state codes
        :param internal_id: Optional. A unique ID for the instance. Need not be
                            related to the Instance.uuid.
        """
        self.state = state
        self.internal_id = internal_id

    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.__dict__ == other.__dict__)


def _score_cpu_topology(topology, wanttopology):
    """Compare a topology against a desired configuration.

    Calculate a score indicating how well a provided topology matches
    against a preferred topology, where:

     a score of 3 indicates an exact match for sockets, cores and
       threads
     a score of 2 indicates a match of sockets and cores, or sockets
       and threads, or cores and threads
     a score of 1 indicates a match of sockets or cores or threads
     a score of 0 indicates no match

    :param wanttopology: nova.objects.VirtCPUTopology instance for
                         preferred topology

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

    Extracts the topology constraints from the configuration defined in
    the flavor extra specs or the image metadata. In the flavor this
    will look for:

     hw:cpu_sockets - preferred socket count
     hw:cpu_cores - preferred core count
     hw:cpu_threads - preferred thread count
     hw:cpu_max_sockets - maximum socket count
     hw:cpu_max_cores - maximum core count
     hw:cpu_max_threads - maximum thread count

    In the image metadata this will look at:

     hw_cpu_sockets - preferred socket count
     hw_cpu_cores - preferred core count
     hw_cpu_threads - preferred thread count
     hw_cpu_max_sockets - maximum socket count
     hw_cpu_max_cores - maximum core count
     hw_cpu_max_threads - maximum thread count

    The image metadata must be strictly lower than any values set in
    the flavor. All values are, however, optional.

    :param flavor: Flavor object to read extra specs from
    :param image_meta: nova.objects.ImageMeta object instance

    :raises: exception.ImageVCPULimitsRangeExceeded if the maximum
             counts set against the image exceed the maximum counts
             set against the flavor
    :raises: exception.ImageVCPUTopologyRangeExceeded if the preferred
             counts set against the image exceed the maximum counts set
             against the image or flavor
    :returns: A two-tuple of objects.VirtCPUTopology instances. The
              first element corresponds to the preferred topology,
              while the latter corresponds to the maximum topology,
              based on upper limits.
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
    props = image_meta.properties
    maxsockets = props.get("hw_cpu_max_sockets", flvmaxsockets)
    maxcores = props.get("hw_cpu_max_cores", flvmaxcores)
    maxthreads = props.get("hw_cpu_max_threads", flvmaxthreads)

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
    sockets = props.get("hw_cpu_sockets", -1)
    cores = props.get("hw_cpu_cores", -1)
    threads = props.get("hw_cpu_threads", -1)

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


def _get_possible_cpu_topologies(vcpus, maxtopology,
                                 allow_threads):
    """Get a list of possible topologies for a vCPU count.

    Given a total desired vCPU count and constraints on the maximum
    number of sockets, cores and threads, return a list of
    objects.VirtCPUTopology instances that represent every possible
    topology that satisfies the constraints.

    :param vcpus: total number of CPUs for guest instance
    :param maxtopology: objects.VirtCPUTopology instance for upper
                        limits
    :param allow_threads: True if the hypervisor supports CPU threads

    :raises: exception.ImageVCPULimitsRangeImpossible if it is
             impossible to achieve the total vcpu count given
             the maximum limits on sockets, cores and threads
    :returns: list of objects.VirtCPUTopology instances
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
                if (t * c * s) != vcpus:
                    continue
                possible.append(
                    objects.VirtCPUTopology(sockets=s,
                                            cores=c,
                                            threads=t))

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


def _filter_for_numa_threads(possible, wantthreads):
    """Filter topologies which closest match to NUMA threads.

    Determine which topologies provide the closest match to the number
    of threads desired by the NUMA topology of the instance.

    The possible topologies may not have any entries which match the
    desired thread count. This method will find the topologies which
    have the closest matching count. For example, if 'wantthreads' is 4
    and the possible topologies has entries with 6, 3, 2 or 1 threads,
    the topologies which have 3 threads will be identified as the
    closest match not greater than 4 and will be returned.

    :param possible: list of objects.VirtCPUTopology instances
    :param wantthreads: desired number of threads

    :returns: list of objects.VirtCPUTopology instances
    """
    # First figure out the largest available thread
    # count which is not greater than wantthreads
    mostthreads = 0
    for topology in possible:
        if topology.threads > wantthreads:
            continue
        if topology.threads > mostthreads:
            mostthreads = topology.threads

    # Now restrict to just those topologies which
    # match the largest thread count
    bestthreads = []
    for topology in possible:
        if topology.threads != mostthreads:
            continue
        bestthreads.append(topology)

    return bestthreads


def _sort_possible_cpu_topologies(possible, wanttopology):
    """Sort the topologies in order of preference.

    Sort the provided list of possible topologies such that the
    configurations which most closely match the preferred topology are
    first.

    :param possible: list of objects.VirtCPUTopology instances
    :param wanttopology: objects.VirtCPUTopology instance for preferred
                         topology

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


def _get_desirable_cpu_topologies(flavor, image_meta, allow_threads=True,
                                  numa_topology=None):
    """Identify desirable CPU topologies based for given constraints.

    Look at the properties set in the flavor extra specs and the image
    metadata and build up a list of all possible valid CPU topologies
    that can be used in the guest. Then return this list sorted in
    order of preference.

    :param flavor: objects.Flavor instance to query extra specs from
    :param image_meta: nova.objects.ImageMeta object instance
    :param allow_threads: if the hypervisor supports CPU threads
    :param numa_topology: objects.InstanceNUMATopology instance that
                          may contain additional topology constraints
                          (such as threading information) that should
                          be considered

    :returns: sorted list of objects.VirtCPUTopology instances
    """

    LOG.debug("Getting desirable topologies for flavor %(flavor)s "
              "and image_meta %(image_meta)s, allow threads: %(threads)s",
              {"flavor": flavor, "image_meta": image_meta,
               "threads": allow_threads})

    preferred, maximum = _get_cpu_topology_constraints(flavor, image_meta)
    LOG.debug("Topology preferred %(preferred)s, maximum %(maximum)s",
              {"preferred": preferred, "maximum": maximum})

    possible = _get_possible_cpu_topologies(flavor.vcpus,
                                            maximum,
                                            allow_threads)
    LOG.debug("Possible topologies %s", possible)

    if numa_topology:
        min_requested_threads = None
        cell_topologies = [cell.cpu_topology for cell in numa_topology.cells
                           if ('cpu_topology' in cell
                               and cell.cpu_topology)]
        if cell_topologies:
            min_requested_threads = min(
                    topo.threads for topo in cell_topologies)

        if min_requested_threads:
            if preferred.threads != -1:
                min_requested_threads = min(preferred.threads,
                                            min_requested_threads)

            specified_threads = max(1, min_requested_threads)
            LOG.debug("Filtering topologies best for %d threads",
                      specified_threads)

            possible = _filter_for_numa_threads(possible,
                                                specified_threads)
            LOG.debug("Remaining possible topologies %s",
                      possible)

    desired = _sort_possible_cpu_topologies(possible, preferred)
    LOG.debug("Sorted desired topologies %s", desired)
    return desired


def get_best_cpu_topology(flavor, image_meta, allow_threads=True,
                          numa_topology=None):
    """Identify best CPU topology for given constraints.

    Look at the properties set in the flavor extra specs and the image
    metadata and build up a list of all possible valid CPU topologies
    that can be used in the guest. Then return the best topology to use

    :param flavor: objects.Flavor instance to query extra specs from
    :param image_meta: nova.objects.ImageMeta object instance
    :param allow_threads: if the hypervisor supports CPU threads
    :param numa_topology: objects.InstanceNUMATopology instance that
                          may contain additional topology constraints
                          (such as threading information) that should
                          be considered

    :returns: an objects.VirtCPUTopology instance for best topology
    """
    return _get_desirable_cpu_topologies(flavor, image_meta,
                                         allow_threads, numa_topology)[0]


def _numa_cell_supports_pagesize_request(host_cell, inst_cell):
    """Determine whether the cell can accept the request.

    :param host_cell: host cell to fit the instance cell onto
    :param inst_cell: instance cell we want to fit

    :raises: exception.MemoryPageSizeNotSupported if custom page
             size not supported in host cell
    :returns: the page size able to be handled by host_cell
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


def _pack_instance_onto_cores(available_siblings,
                              instance_cell,
                              host_cell_id,
                              threads_per_core=1,
                              num_cpu_reserved=0):
    """Pack an instance onto a set of siblings.

    Calculate the pinning for the given instance and its topology,
    making sure that hyperthreads of the instance match up with those
    of the host when the pinning takes effect. Also ensure that the
    physical cores reserved for hypervisor on this host NUMA node do
    not break any thread policies.

    Currently the strategy for packing is to prefer siblings and try use
    cores evenly by using emptier cores first. This is achieved by the
    way we order cores in the sibling_sets structure, and the order in
    which we iterate through it.

    The main packing loop that iterates over the sibling_sets dictionary
    will not currently try to look for a fit that maximizes number of
    siblings, but will simply rely on the iteration ordering and picking
    the first viable placement.

    :param available_siblings: list of sets of CPU IDs corresponding to
                               available siblings per core
    :param instance_cell: An instance of objects.InstanceNUMACell
                          describing the pinning requirements of the
                          instance
    :param threads_per_core: number of threads per core in host's cell
    :param num_cpu_reserved: number of pCPUs reserved for hypervisor

    :returns: An instance of objects.InstanceNUMACell containing the
              pinning information, the physical cores reserved and
              potentially a new topology to be exposed to the
              instance. None if there is no valid way to satisfy the
              sibling requirements for the instance.

    """
    LOG.debug('Packing an instance onto a set of siblings: '
             '    available_siblings: %(siblings)s'
             '    instance_cell: %(cells)s'
             '    host_cell_id: %(host_cell_id)s'
             '    threads_per_core: %(threads_per_core)s',
                {'siblings': available_siblings,
                 'cells': instance_cell,
                 'host_cell_id': host_cell_id,
                 'threads_per_core': threads_per_core})

    # We build up a data structure that answers the question: 'Given the
    # number of threads I want to pack, give me a list of all the available
    # sibling sets (or groups thereof) that can accommodate it'
    sibling_sets = collections.defaultdict(list)
    for sib in available_siblings:
        for threads_no in range(1, len(sib) + 1):
            sibling_sets[threads_no].append(sib)
    LOG.debug('Built sibling_sets: %(siblings)s', {'siblings': sibling_sets})

    pinning = None
    threads_no = 1

    def _orphans(instance_cell, threads_per_core):
        """Number of instance CPUs which will not fill up a host core.

        Best explained by an example: consider set of free host cores as such:
            [(0, 1), (3, 5), (6, 7, 8)]
        This would be a case of 2 threads_per_core AKA an entry for 2 in the
        sibling_sets structure.

        If we attempt to pack a 5 core instance on it - due to the fact that we
        iterate the list in order, we will end up with a single core of the
        instance pinned to a thread "alone" (with id 6), and we would have one
        'orphan' vcpu.
        """
        return len(instance_cell) % threads_per_core

    def _threads(instance_cell, threads_per_core):
        """Threads to expose to the instance via the VirtCPUTopology.

        This is calculated by taking the GCD of the number of threads we are
        considering at the moment, and the number of orphans. An example for
            instance_cell = 6
            threads_per_core = 4

        So we can fit the instance as such:
            [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11)]
              x  x  x  x    x  x

        We can't expose 4 threads, as that will not be a valid topology (all
        cores exposed to the guest have to have an equal number of threads),
        and 1 would be too restrictive, but we want all threads that guest sees
        to be on the same physical core, so we take GCD of 4 (max number of
        threads) and 2 (number of 'orphan' CPUs) and get 2 as the number of
        threads.
        """
        return fractions.gcd(threads_per_core, _orphans(instance_cell,
                                                        threads_per_core))

    def _get_pinning(threads_no, sibling_set, instance_cores,
                     num_cpu_reserved=0):
        """Determines pCPUs/vCPUs mapping

        Determines the pCPUs/vCPUs mapping regarding the number of
        threads which can be used per cores and pCPUs reserved.

        :param threads_no: Number of host threads per cores which can
                           be used to pin vCPUs according to the
                           policies.
        :param sibling_set: List of available threads per host cores
                            on a specific host NUMA node.
        :param instance_cores: Set of vCPUs requested.
        :param num_cpu_reserved: Number of additional host CPUs which
                                 needs to be reserved.

        NOTE: Depending on how host is configured (HT/non-HT) a thread can
              be considered as an entire core.
        """
        if threads_no * len(sibling_set) < (
                len(instance_cores) + num_cpu_reserved):
            return None, None

        # Determines usable cores according the "threads number"
        # constraint.
        #
        # For a sibling_set=[(0, 1, 2, 3), (4, 5, 6, 7)] and thread_no 1:
        # usable_cores=[(0), (4),]
        #
        # For a sibling_set=[(0, 1, 2, 3), (4, 5, 6, 7)] and thread_no 2:
        # usable_cores=[(0, 1), (4, 5)]
        usable_cores = list(map(lambda s: list(s)[:threads_no], sibling_set))

        # Determines the mapping vCPUs/pCPUs based on the sets of
        # usable cores.
        #
        # For an instance_cores=[2, 3], usable_cores=[(0), (4)]
        # vcpus_pinning=[(2, 0), (3, 4)]
        vcpus_pinning = list(zip(sorted(instance_cores),
                                 itertools.chain(*usable_cores)))
        msg = ("Computed NUMA topology CPU pinning: usable pCPUs: "
               "%(usable_cores)s, vCPUs mapping: %(vcpus_pinning)s")
        msg_args = {
            'usable_cores': usable_cores,
            'vcpus_pinning': vcpus_pinning,
        }
        LOG.info(msg, msg_args)

        cpuset_reserved = None
        if num_cpu_reserved:
            # Updates the pCPUs used based on vCPUs pinned to
            #
            # For vcpus_pinning=[(0, 2), (1, 3)], usable_cores=[(2, 3), (4, 5)]
            # usable_cores=[(), (4, 5)]
            for vcpu, pcpu in vcpus_pinning:
                for sib in usable_cores:
                    if pcpu in sib:
                        sib.remove(pcpu)

            # Determines the pCPUs reserved for hypervisor
            #
            # For usable_cores=[(), (4, 5)], num_cpu_reserved=1
            # cpuset_reserved=[4]
            cpuset_reserved = set(list(
                itertools.chain(*usable_cores))[:num_cpu_reserved])
            msg = ("Computed NUMA topology reserved pCPUs: usable pCPUs: "
                   "%(usable_cores)s, reserved pCPUs: %(cpuset_reserved)s")
            msg_args = {
                'usable_cores': usable_cores,
                'cpuset_reserved': cpuset_reserved,
            }
            LOG.info(msg, msg_args)

        return vcpus_pinning, cpuset_reserved

    if (instance_cell.cpu_thread_policy ==
            fields.CPUThreadAllocationPolicy.REQUIRE):
        LOG.debug("Requested 'require' thread policy for %d cores",
                  len(instance_cell))
    elif (instance_cell.cpu_thread_policy ==
            fields.CPUThreadAllocationPolicy.PREFER):
        LOG.debug("Requested 'prefer' thread policy for %d cores",
                  len(instance_cell))
    elif (instance_cell.cpu_thread_policy ==
            fields.CPUThreadAllocationPolicy.ISOLATE):
        LOG.debug("Requested 'isolate' thread policy for %d cores",
                  len(instance_cell))
    else:
        LOG.debug("User did not specify a thread policy. Using default "
                  "for %d cores", len(instance_cell))

    if (instance_cell.cpu_thread_policy ==
            fields.CPUThreadAllocationPolicy.ISOLATE):
        # make sure we have at least one fully free core
        if threads_per_core not in sibling_sets:
            LOG.debug('Host does not have any fully free thread sibling sets.'
                      'It is not possible to emulate a non-SMT behavior '
                      'for the isolate policy without this.')
            return

        pinning, cpuset_reserved = _get_pinning(
            1,  # we only want to "use" one thread per core
            sibling_sets[threads_per_core],
            instance_cell.cpuset,
            num_cpu_reserved=num_cpu_reserved)
    else:  # REQUIRE, PREFER (explicit, implicit)
        # NOTE(ndipanov): We iterate over the sibling sets in descending order
        # of cores that can be packed. This is an attempt to evenly distribute
        # instances among physical cores
        for threads_no, sibling_set in sorted(
                (t for t in sibling_sets.items()), reverse=True):

            # NOTE(sfinucan): The key difference between the require and
            # prefer policies is that require will not settle for non-siblings
            # if this is all that is available. Enforce this by ensuring we're
            # using sibling sets that contain at least one sibling
            if (instance_cell.cpu_thread_policy ==
                    fields.CPUThreadAllocationPolicy.REQUIRE):
                if threads_no <= 1:
                    LOG.debug('Skipping threads_no: %s, as it does not satisfy'
                              ' the require policy', threads_no)
                    continue

            pinning, cpuset_reserved = _get_pinning(
                threads_no, sibling_set,
                instance_cell.cpuset,
                num_cpu_reserved=num_cpu_reserved)
            if pinning:
                break

        # NOTE(sfinucan): If siblings weren't available and we're using PREFER
        # (implicitly or explicitly), fall back to linear assignment across
        # cores
        if (instance_cell.cpu_thread_policy !=
                fields.CPUThreadAllocationPolicy.REQUIRE and
                not pinning):
            pinning = list(zip(sorted(instance_cell.cpuset),
                               itertools.chain(*sibling_set)))

        threads_no = _threads(instance_cell, threads_no)

    if not pinning:
        return
    LOG.debug('Selected cores for pinning: %s, in cell %s', pinning,
                                                            host_cell_id)

    topology = objects.VirtCPUTopology(sockets=1,
                                       cores=len(pinning) // threads_no,
                                       threads=threads_no)
    instance_cell.pin_vcpus(*pinning)
    instance_cell.cpu_topology = topology
    instance_cell.id = host_cell_id
    instance_cell.cpuset_reserved = cpuset_reserved
    return instance_cell


def _numa_fit_instance_cell_with_pinning(host_cell, instance_cell,
                                         num_cpu_reserved=0):
    """Determine if cells can be pinned to a host cell.

    :param host_cell: objects.NUMACell instance - the host cell that
                      the instance should be pinned to
    :param instance_cell: objects.InstanceNUMACell instance without any
                          pinning information
    :param num_cpu_reserved: int - number of pCPUs reserved for hypervisor

    :returns: objects.InstanceNUMACell instance with pinning information,
              or None if instance cannot be pinned to the given host
    """
    required_cpus = len(instance_cell.cpuset) + num_cpu_reserved
    if host_cell.avail_cpus < required_cpus:
        LOG.debug('Not enough available CPUs to schedule instance. '
                  'Oversubscription is not possible with pinned instances. '
                  'Required: %(required)d (%(vcpus)d + %(num_cpu_reserved)d), '
                  'actual: %(actual)d',
                  {'required': required_cpus,
                   'vcpus': len(instance_cell.cpuset),
                   'actual': host_cell.avail_cpus,
                   'num_cpu_reserved': num_cpu_reserved})
        return

    if host_cell.avail_memory < instance_cell.memory:
        LOG.debug('Not enough available memory to schedule instance. '
                  'Oversubscription is not possible with pinned instances. '
                  'Required: %(required)s, available: %(available)s, '
                  'total: %(total)s. ',
                  {'required': instance_cell.memory,
                   'available': host_cell.avail_memory,
                   'total': host_cell.memory})
        return

    if host_cell.siblings:
        LOG.debug('Using thread siblings for packing')
        # Try to pack the instance cell onto cores
        numa_cell = _pack_instance_onto_cores(
            host_cell.free_siblings, instance_cell, host_cell.id,
            max(map(len, host_cell.siblings)),
            num_cpu_reserved=num_cpu_reserved)
    else:
        if (instance_cell.cpu_thread_policy ==
                fields.CPUThreadAllocationPolicy.REQUIRE):
            LOG.info("Host does not support hyperthreading or "
                     "hyperthreading is disabled, but 'require' "
                     "threads policy was requested.")
            return

        # Straightforward to pin to available cpus when there is no
        # hyperthreading on the host
        free_cpus = [set([cpu]) for cpu in host_cell.free_cpus]
        numa_cell = _pack_instance_onto_cores(
            free_cpus, instance_cell, host_cell.id,
            num_cpu_reserved=num_cpu_reserved)

    if not numa_cell:
        LOG.debug('Failed to map instance cell CPUs to host cell CPUs')

    return numa_cell


def _numa_fit_instance_cell(host_cell, instance_cell, limit_cell=None,
                            cpuset_reserved=0):
    """Ensure an instance cell can fit onto a host cell

    Ensure an instance cell can fit onto a host cell and, if so, return
    a new objects.InstanceNUMACell with the id set to that of the host.
    Returns None if the instance cell exceeds the limits of the host.

    :param host_cell: host cell to fit the instance cell onto
    :param instance_cell: instance cell we want to fit
    :param limit_cell: an objects.NUMATopologyLimit or None
    :param cpuset_reserved: An int to indicate the number of CPUs overhead

    :returns: objects.InstanceNUMACell with the id set to that of the
              host, or None
    """
    LOG.debug('Attempting to fit instance cell %(cell)s on host_cell '
              '%(host_cell)s', {'cell': instance_cell, 'host_cell': host_cell})
    # NOTE (ndipanov): do not allow an instance to overcommit against
    # itself on any NUMA cell
    if instance_cell.memory > host_cell.memory:
        LOG.debug('Not enough host cell memory to fit instance cell. '
                  'Required: %(required)d, actual: %(actual)d',
                  {'required': instance_cell.memory,
                   'actual': host_cell.memory})
        return

    if len(instance_cell.cpuset) + cpuset_reserved > len(host_cell.cpuset):
        LOG.debug('Not enough host cell CPUs to fit instance cell. Required: '
                  '%(required)d + %(cpuset_reserved)d as overhead, '
                  'actual: %(actual)d',
                  {'required': len(instance_cell.cpuset),
                   'actual': len(host_cell.cpuset),
                   'cpuset_reserved': cpuset_reserved})
        return

    if instance_cell.cpu_pinning_requested:
        LOG.debug('Pinning has been requested')
        new_instance_cell = _numa_fit_instance_cell_with_pinning(
            host_cell, instance_cell, cpuset_reserved)
        if not new_instance_cell:
            return
        new_instance_cell.pagesize = instance_cell.pagesize
        instance_cell = new_instance_cell

    elif limit_cell:
        LOG.debug('No pinning requested, considering limitations on usable cpu'
                  ' and memory')
        memory_usage = host_cell.memory_usage + instance_cell.memory
        cpu_usage = host_cell.cpu_usage + len(instance_cell.cpuset)
        cpu_limit = len(host_cell.cpuset) * limit_cell.cpu_allocation_ratio
        ram_limit = host_cell.memory * limit_cell.ram_allocation_ratio
        if memory_usage > ram_limit:
            LOG.debug('Host cell has limitations on usable memory. There is '
                      'not enough free memory to schedule this instance. '
                      'Usage: %(usage)d, limit: %(limit)d',
                      {'usage': memory_usage, 'limit': ram_limit})
            return
        if cpu_usage > cpu_limit:
            LOG.debug('Host cell has limitations on usable CPUs. There are '
                      'not enough free CPUs to schedule this instance. '
                      'Usage: %(usage)d, limit: %(limit)d',
                      {'usage': cpu_usage, 'limit': cpu_limit})
            return

    pagesize = None
    if instance_cell.pagesize:
        pagesize = _numa_cell_supports_pagesize_request(
            host_cell, instance_cell)
        if not pagesize:
            LOG.debug('Host does not support requested memory pagesize. '
                      'Requested: %d kB', instance_cell.pagesize)
            return
        LOG.debug('Selected memory pagesize: %(selected_mem_pagesize)d kB. '
                  'Requested memory pagesize: %(requested_mem_pagesize)d '
                   '(small = -1, large = -2, any = -3)',
                  {'selected_mem_pagesize': pagesize,
                   'requested_mem_pagesize': instance_cell.pagesize})

    instance_cell.id = host_cell.id
    instance_cell.pagesize = pagesize
    return instance_cell


def _get_flavor_image_meta(key, flavor, image_meta):
    """Extract both flavor- and image-based variants of metadata."""
    flavor_key = ':'.join(['hw', key])
    image_key = '_'.join(['hw', key])

    flavor_policy = flavor.get('extra_specs', {}).get(flavor_key)
    image_policy = image_meta.properties.get(image_key)

    return flavor_policy, image_policy


def _numa_get_pagesize_constraints(flavor, image_meta):
    """Return the requested memory page size

    :param flavor: a Flavor object to read extra specs from
    :param image_meta: nova.objects.ImageMeta object instance

    :raises: MemoryPageSizeInvalid if flavor extra spec or image
             metadata provides an invalid hugepage value
    :raises: MemoryPageSizeForbidden if flavor extra spec request
             conflicts with image metadata request
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
                try:
                    request = strutils.string_to_bytes(
                        request, return_int=True) / units.Ki
                except ValueError:
                    request = 0

        if request <= 0:
            raise exception.MemoryPageSizeInvalid(pagesize=request)

        return request

    flavor_request, image_request = _get_flavor_image_meta(
        'mem_page_size', flavor, image_meta)

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


def _numa_get_flavor_numa_map(flavor, key, func):
    hw_numa_map = []
    extra_specs = flavor.get('extra_specs', {})
    for cellid in range(objects.ImageMetaProps.NUMA_NODES_MAX):
        prop = '%s.%d' % (key, cellid)
        if prop not in extra_specs:
            break
        hw_numa_map.append(func(extra_specs[prop]))

    return hw_numa_map or None


def _numa_get_cpu_map_list(flavor, image_meta):
    flavor_cpu_list = _numa_get_flavor_numa_map(flavor, 'hw:numa_cpus',
                                                parse_cpu_spec)
    image_cpu_list = image_meta.properties.get('hw_numa_cpus', None)

    if flavor_cpu_list is None:
        return image_cpu_list

    if image_cpu_list is not None:
        raise exception.ImageNUMATopologyForbidden(
            name='hw_numa_cpus')

    return flavor_cpu_list


def _numa_get_mem_map_list(flavor, image_meta):
    flavor_mem_list = _numa_get_flavor_numa_map(flavor, 'hw:numa_mem', int)
    image_mem_list = image_meta.properties.get('hw_numa_mem', None)

    if flavor_mem_list is None:
        return image_mem_list

    if image_mem_list is not None:
        raise exception.ImageNUMATopologyForbidden(
            name='hw_numa_mem')

    return flavor_mem_list


def _get_cpu_policy_constraints(flavor, image_meta):
    """Validate and return the requested CPU policy."""
    flavor_policy, image_policy = _get_flavor_image_meta(
        'cpu_policy', flavor, image_meta)

    if flavor_policy == fields.CPUAllocationPolicy.DEDICATED:
        cpu_policy = flavor_policy
    elif flavor_policy == fields.CPUAllocationPolicy.SHARED:
        if image_policy == fields.CPUAllocationPolicy.DEDICATED:
            raise exception.ImageCPUPinningForbidden()
        cpu_policy = flavor_policy
    elif image_policy == fields.CPUAllocationPolicy.DEDICATED:
        cpu_policy = image_policy
    else:
        cpu_policy = fields.CPUAllocationPolicy.SHARED

    return cpu_policy


def _get_cpu_thread_policy_constraints(flavor, image_meta):
    """Validate and return the requested CPU thread policy."""
    flavor_policy, image_policy = _get_flavor_image_meta(
        'cpu_thread_policy', flavor, image_meta)

    if flavor_policy in [None, fields.CPUThreadAllocationPolicy.PREFER]:
        policy = flavor_policy or image_policy
    elif image_policy and image_policy != flavor_policy:
        raise exception.ImageCPUThreadPolicyForbidden()
    else:
        policy = flavor_policy

    return policy


def _numa_get_constraints_manual(nodes, flavor, cpu_list, mem_list):
    cells = []
    totalmem = 0

    availcpus = set(range(flavor.vcpus))

    for node in range(nodes):
        mem = mem_list[node]
        cpuset = cpu_list[node]

        for cpu in cpuset:
            if cpu > (flavor.vcpus - 1):
                raise exception.ImageNUMATopologyCPUOutOfRange(
                    cpunum=cpu, cpumax=(flavor.vcpus - 1))

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

    if totalmem != flavor.memory_mb:
        raise exception.ImageNUMATopologyMemoryOutOfRange(
            memsize=totalmem,
            memtotal=flavor.memory_mb)

    return objects.InstanceNUMATopology(cells=cells)


def is_realtime_enabled(flavor):
    flavor_rt = flavor.get('extra_specs', {}).get("hw:cpu_realtime")
    return strutils.bool_from_string(flavor_rt)


def _get_realtime_mask(flavor, image):
    """Returns realtime mask based on flavor/image meta"""
    flavor_mask, image_mask = _get_flavor_image_meta(
        'cpu_realtime_mask', flavor, image)

    # Image masks are used ahead of flavor masks as they will have more
    # specific requirements
    return image_mask or flavor_mask


def vcpus_realtime_topology(flavor, image):
    """Determines instance vCPUs used as RT for a given spec"""
    mask = _get_realtime_mask(flavor, image)
    if not mask:
        raise exception.RealtimeMaskNotFoundOrInvalid()

    vcpus_rt = parse_cpu_spec("0-%d,%s" % (flavor.vcpus - 1, mask))
    if len(vcpus_rt) < 1:
        raise exception.RealtimeMaskNotFoundOrInvalid()

    return vcpus_rt


def _numa_get_constraints_auto(nodes, flavor):
    if ((flavor.vcpus % nodes) > 0 or
        (flavor.memory_mb % nodes) > 0):
        raise exception.ImageNUMATopologyAsymmetric()

    cells = []
    for node in range(nodes):
        ncpus = int(flavor.vcpus / nodes)
        mem = int(flavor.memory_mb / nodes)
        start = node * ncpus
        cpuset = set(range(start, start + ncpus))

        cells.append(objects.InstanceNUMACell(
            id=node, cpuset=cpuset, memory=mem))

    return objects.InstanceNUMATopology(cells=cells)


def get_emulator_threads_constraint(flavor, image_meta):
    """Determines the emulator threads policy"""
    emu_threads_policy = flavor.get('extra_specs', {}).get(
        'hw:emulator_threads_policy')
    LOG.debug("emulator threads policy constraint: %s", emu_threads_policy)

    if not emu_threads_policy:
        return

    if emu_threads_policy not in fields.CPUEmulatorThreadsPolicy.ALL:
        raise exception.InvalidEmulatorThreadsPolicy(
            requested=emu_threads_policy,
            available=str(fields.CPUEmulatorThreadsPolicy.ALL))

    if emu_threads_policy == fields.CPUEmulatorThreadsPolicy.ISOLATE:
        # In order to make available emulator threads policy, a dedicated
        # CPU policy is necessary.
        cpu_policy = _get_cpu_policy_constraints(flavor, image_meta)
        if cpu_policy != fields.CPUAllocationPolicy.DEDICATED:
            raise exception.BadRequirementEmulatorThreadsPolicy()

    return emu_threads_policy


def _validate_numa_nodes(nodes):
    """Validate NUMA nodes number

    :param nodes: number of NUMA nodes

    :raises: exception.InvalidNUMANodesNumber if the number of NUMA
             nodes is less than 1 or not an integer
    """
    if nodes is not None and (not strutils.is_int_like(nodes) or
       int(nodes) < 1):
        raise exception.InvalidNUMANodesNumber(nodes=nodes)


# TODO(sahid): Move numa related to hardware/numa.py
def numa_get_constraints(flavor, image_meta):
    """Return topology related to input request.

    :param flavor: a flavor object to read extra specs from
    :param image_meta: nova.objects.ImageMeta object instance

    :raises: exception.InvalidNUMANodesNumber if the number of NUMA
             nodes is less than 1 or not an integer
    :raises: exception.ImageNUMATopologyForbidden if an attempt is made
             to override flavor settings with image properties
    :raises: exception.MemoryPageSizeInvalid if flavor extra spec or
             image metadata provides an invalid hugepage value
    :raises: exception.MemoryPageSizeForbidden if flavor extra spec
             request conflicts with image metadata request
    :raises: exception.ImageNUMATopologyIncomplete if the image
             properties are not correctly specified
    :raises: exception.ImageNUMATopologyAsymmetric if the number of
             NUMA nodes is not a factor of the requested total CPUs or
             memory
    :raises: exception.ImageNUMATopologyCPUOutOfRange if an instance
             CPU given in a NUMA mapping is not valid
    :raises: exception.ImageNUMATopologyCPUDuplicates if an instance
             CPU is specified in CPU mappings for two NUMA nodes
    :raises: exception.ImageNUMATopologyCPUsUnassigned if an instance
             CPU given in a NUMA mapping is not assigned to any NUMA node
    :raises: exception.ImageNUMATopologyMemoryOutOfRange if sum of memory from
             each NUMA node is not equal with total requested memory
    :raises: exception.ImageCPUPinningForbidden if a CPU policy
             specified in a flavor conflicts with one defined in image
             metadata
    :raises: exception.RealtimeConfigurationInvalid if realtime is
             requested but dedicated CPU policy is not also requested
    :raises: exception.RealtimeMaskNotFoundOrInvalid if realtime is
             requested but no mask provided
    :raises: exception.CPUThreadPolicyConfigurationInvalid if a CPU thread
             policy conflicts with CPU allocation policy
    :raises: exception.ImageCPUThreadPolicyForbidden if a CPU thread policy
             specified in a flavor conflicts with one defined in image metadata
    :returns: objects.InstanceNUMATopology, or None
    """
    flavor_nodes, image_nodes = _get_flavor_image_meta(
        'numa_nodes', flavor, image_meta)
    if flavor_nodes and image_nodes:
        raise exception.ImageNUMATopologyForbidden(
            name='hw_numa_nodes')

    nodes = None
    if flavor_nodes:
        _validate_numa_nodes(flavor_nodes)
        nodes = int(flavor_nodes)
    else:
        _validate_numa_nodes(image_nodes)
        nodes = image_nodes

    pagesize = _numa_get_pagesize_constraints(
        flavor, image_meta)

    numa_topology = None
    if nodes or pagesize:
        nodes = nodes or 1

        cpu_list = _numa_get_cpu_map_list(flavor, image_meta)
        mem_list = _numa_get_mem_map_list(flavor, image_meta)

        # If one property list is specified both must be
        if ((cpu_list is None and mem_list is not None) or
            (cpu_list is not None and mem_list is None)):
            raise exception.ImageNUMATopologyIncomplete()

        # If any node has data set, all nodes must have data set
        if ((cpu_list is not None and len(cpu_list) != nodes) or
            (mem_list is not None and len(mem_list) != nodes)):
            raise exception.ImageNUMATopologyIncomplete()

        if cpu_list is None:
            numa_topology = _numa_get_constraints_auto(
                nodes, flavor)
        else:
            numa_topology = _numa_get_constraints_manual(
                nodes, flavor, cpu_list, mem_list)

        # We currently support same pagesize for all cells.
        for c in numa_topology.cells:
            setattr(c, 'pagesize', pagesize)

    cpu_policy = _get_cpu_policy_constraints(flavor, image_meta)
    cpu_thread_policy = _get_cpu_thread_policy_constraints(flavor, image_meta)
    rt_mask = _get_realtime_mask(flavor, image_meta)
    emu_thread_policy = get_emulator_threads_constraint(flavor, image_meta)

    # sanity checks

    rt = is_realtime_enabled(flavor)

    if rt and cpu_policy != fields.CPUAllocationPolicy.DEDICATED:
        raise exception.RealtimeConfigurationInvalid()

    if rt and not rt_mask:
        raise exception.RealtimeMaskNotFoundOrInvalid()

    if cpu_policy == fields.CPUAllocationPolicy.SHARED:
        if cpu_thread_policy:
            raise exception.CPUThreadPolicyConfigurationInvalid()
        return numa_topology

    if numa_topology:
        for cell in numa_topology.cells:
            cell.cpu_policy = cpu_policy
            cell.cpu_thread_policy = cpu_thread_policy
    else:
        single_cell = objects.InstanceNUMACell(
            id=0,
            cpuset=set(range(flavor.vcpus)),
            memory=flavor.memory_mb,
            cpu_policy=cpu_policy,
            cpu_thread_policy=cpu_thread_policy)
        numa_topology = objects.InstanceNUMATopology(cells=[single_cell])

    if emu_thread_policy:
        numa_topology.emulator_threads_policy = emu_thread_policy

    return numa_topology


def numa_fit_instance_to_host(
        host_topology, instance_topology, limits=None,
        pci_requests=None, pci_stats=None):
    """Fit the instance topology onto the host topology.

    Given a host, instance topology, and (optional) limits, attempt to
    fit instance cells onto all permutations of host cells by calling
    the _fit_instance_cell method, and return a new InstanceNUMATopology
    with its cell ids set to host cell ids of the first successful
    permutation, or None.

    :param host_topology: objects.NUMATopology object to fit an
                          instance on
    :param instance_topology: objects.InstanceNUMATopology to be fitted
    :param limits: objects.NUMATopologyLimits that defines limits
    :param pci_requests: instance pci_requests
    :param pci_stats: pci_stats for the host

    :returns: objects.InstanceNUMATopology with its cell IDs set to host
              cell ids of the first successful permutation, or None
    """
    if not (host_topology and instance_topology):
        LOG.debug("Require both a host and instance NUMA topology to "
                  "fit instance on host.")
        return
    elif len(host_topology) < len(instance_topology):
        LOG.debug("There are not enough NUMA nodes on the system to schedule "
                  "the instance correctly. Required: %(required)s, actual: "
                  "%(actual)s",
                  {'required': len(instance_topology),
                   'actual': len(host_topology)})
        return

    emulator_threads_policy = None
    if 'emulator_threads_policy' in instance_topology:
        emulator_threads_policy = instance_topology.emulator_threads_policy

    host_cells = host_topology.cells

    # If PCI device(s) are not required, prefer host cells that don't have
    # devices attached. Presence of a given numa_node in a PCI pool is
    # indicative of a PCI device being associated with that node
    if not pci_requests and pci_stats:
        host_cells = sorted(host_cells, key=lambda cell: cell.id in [
            pool['numa_node'] for pool in pci_stats.pools])

    # TODO(ndipanov): We may want to sort permutations differently
    # depending on whether we want packing/spreading over NUMA nodes
    for host_cell_perm in itertools.permutations(
            host_cells, len(instance_topology)):
        cells = []
        for host_cell, instance_cell in zip(
                host_cell_perm, instance_topology.cells):
            try:
                cpuset_reserved = 0
                if (instance_topology.emulator_threads_isolated
                    and len(cells) == 0):
                    # For the case of isolate emulator threads, to
                    # make predictable where that CPU overhead is
                    # located we always configure it to be on host
                    # NUMA node associated to the guest NUMA node
                    # 0.
                    cpuset_reserved = 1
                got_cell = _numa_fit_instance_cell(
                    host_cell, instance_cell, limits, cpuset_reserved)
            except exception.MemoryPageSizeNotSupported:
                # This exception will been raised if instance cell's
                # custom pagesize is not supported with host cell in
                # _numa_cell_supports_pagesize_request function.
                break
            if got_cell is None:
                break
            cells.append(got_cell)

        if len(cells) != len(host_cell_perm):
            continue

        if not pci_requests or ((pci_stats is not None) and
                pci_stats.support_requests(pci_requests, cells)):
            return objects.InstanceNUMATopology(
                cells=cells,
                emulator_threads_policy=emulator_threads_policy)


def numa_get_reserved_huge_pages():
    """Returns reserved memory pages from host option.

    Based from the compute node option reserved_huge_pages, generate
    a well formatted list of dict which can be used to build a valid
    NUMATopology.

    :raises: exception.InvalidReservedMemoryPagesOption when
             reserved_huge_pages option is not correctly set.
    :returns: a list of dict ordered by NUMA node ids; keys of dict
              are pages size and values of the number reserved.
    """
    if not CONF.reserved_huge_pages:
        return {}

    try:
        bucket = collections.defaultdict(dict)
        for cfg in CONF.reserved_huge_pages:
            try:
                pagesize = int(cfg['size'])
            except ValueError:
                pagesize = strutils.string_to_bytes(
                    cfg['size'], return_int=True) / units.Ki
            bucket[int(cfg['node'])][pagesize] = int(cfg['count'])
    except (ValueError, TypeError, KeyError):
        raise exception.InvalidReservedMemoryPagesOption(
            conf=CONF.reserved_huge_pages)

    return bucket


def _numa_pagesize_usage_from_cell(hostcell, instancecell, sign):
    topo = []
    for pages in hostcell.mempages:
        if pages.size_kb == instancecell.pagesize:
            topo.append(objects.NUMAPagesTopology(
                size_kb=pages.size_kb,
                total=pages.total,
                used=max(0, pages.used +
                         instancecell.memory * units.Ki /
                         pages.size_kb * sign),
                reserved=pages.reserved if 'reserved' in pages else 0))
        else:
            topo.append(pages)
    return topo


def numa_usage_from_instances(host, instances, free=False):
    """Get host topology usage.

    Sum the usage from all provided instances to report the overall
    host topology usage.

    :param host: objects.NUMATopology with usage information
    :param instances: list of objects.InstanceNUMATopology
    :param free: decrease, rather than increase, host usage

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

        newcell = objects.NUMACell(
            id=hostcell.id, cpuset=hostcell.cpuset, memory=hostcell.memory,
            cpu_usage=0, memory_usage=0, mempages=hostcell.mempages,
            pinned_cpus=hostcell.pinned_cpus, siblings=hostcell.siblings)

        for instance in instances:
            for cellid, instancecell in enumerate(instance.cells):
                if instancecell.id != hostcell.id:
                    continue

                memory_usage = memory_usage + sign * instancecell.memory
                cpu_usage_diff = len(instancecell.cpuset)
                if (instancecell.cpu_thread_policy ==
                        fields.CPUThreadAllocationPolicy.ISOLATE and
                        hostcell.siblings):
                    cpu_usage_diff *= max(map(len, hostcell.siblings))
                cpu_usage += sign * cpu_usage_diff

                if (cellid == 0
                    and instance.emulator_threads_isolated):
                    # The emulator threads policy when defined
                    # with 'isolate' makes the instance to consume
                    # an additional pCPU as overhead. That pCPU is
                    # mapped on the host NUMA node related to the
                    # guest NUMA node 0.
                    cpu_usage += sign * len(instancecell.cpuset_reserved)

                if instancecell.pagesize and instancecell.pagesize > 0:
                    newcell.mempages = _numa_pagesize_usage_from_cell(
                        newcell, instancecell, sign)

                if instance.cpu_pinning_requested:
                    pinned_cpus = set(instancecell.cpu_pinning.values())

                    if instancecell.cpuset_reserved:
                        pinned_cpus |= instancecell.cpuset_reserved

                    if free:
                        if (instancecell.cpu_thread_policy ==
                                fields.CPUThreadAllocationPolicy.ISOLATE):
                            newcell.unpin_cpus_with_siblings(pinned_cpus)
                        else:
                            newcell.unpin_cpus(pinned_cpus)
                    else:
                        if (instancecell.cpu_thread_policy ==
                                fields.CPUThreadAllocationPolicy.ISOLATE):
                            newcell.pin_cpus_with_siblings(pinned_cpus)
                        else:
                            newcell.pin_cpus(pinned_cpus)

        newcell.cpu_usage = max(0, cpu_usage)
        newcell.memory_usage = max(0, memory_usage)
        cells.append(newcell)

    return objects.NUMATopology(cells=cells)


# TODO(ndipanov): Remove when all code paths are using objects
def instance_topology_from_instance(instance):
    """Extract numa topology from myriad instance representations.

    Until the RPC version is bumped to 5.x, an instance may be
    represented as a dict, a db object, or an actual Instance object.
    Identify the type received and return either an instance of
    objects.InstanceNUMATopology if the instance's NUMA topology is
    available, else None.

    :param host: nova.objects.ComputeNode instance, or a db object or
                 dict

    :returns: An instance of objects.NUMATopology or None
    """
    if isinstance(instance, obj_instance.Instance):
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
                    pagesize=cell.get('pagesize'),
                    cpu_topology=cell.get('cpu_topology'),
                    cpu_pinning=cell.get('cpu_pinning_raw'),
                    cpu_policy=cell.get('cpu_policy'),
                    cpu_thread_policy=cell.get('cpu_thread_policy'),
                    cpuset_reserved=cell.get('cpuset_reserved'))
                         for cell in dict_cells]
                emulator_threads_policy = instance_numa_topology.get(
                    'emulator_threads_policy')
                instance_numa_topology = objects.InstanceNUMATopology(
                    cells=cells,
                    emulator_threads_policy=emulator_threads_policy)

    return instance_numa_topology


# TODO(ndipanov): Remove when all code paths are using objects
def host_topology_and_format_from_host(host):
    """Extract numa topology from myriad host representations.

    Until the RPC version is bumped to 5.x, a host may be represented
    as a dict, a db object, an actual ComputeNode object, or an
    instance of HostState class. Identify the type received and return
    either an instance of objects.NUMATopology if host's NUMA topology
    is available, else None.

    :returns: A two-tuple. The first element is either an instance of
              objects.NUMATopology or None. The second element is a
              boolean set to True if topology was in JSON format.
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
    """Calculate new host NUMA usage from an instance's NUMA usage.

    Until the RPC version is bumped to 5.x, both host and instance
    representations may be provided in a variety of formats. Extract
    both host and instance numa topologies from provided
    representations, and use the latter to update the NUMA usage
    information of the former.

    :param host: nova.objects.ComputeNode instance, or a db object or
                 dict
    :param instance: nova.objects.Instance instance, or a db object or
                     dict
    :param free: if True the returned topology will have its usage
                 decreased instead
    :param never_serialize_result: if True result will always be an
                                   instance of objects.NUMATopology

    :returns: a objects.NUMATopology instance if never_serialize_result
              was True, else numa_usage in the format it was on the
              host
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
