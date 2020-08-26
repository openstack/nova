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
import math
import re
import typing as ty

import os_resource_classes as orc
import os_traits
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import units
import six

import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import fields
from nova.pci import stats


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

MEMPAGES_SMALL = -1
MEMPAGES_LARGE = -2
MEMPAGES_ANY = -3


class VTPMConfig(ty.NamedTuple):
    version: str
    model: str


def get_vcpu_pin_set():
    """Parse ``vcpu_pin_set`` config.

    :returns: A set of host CPU IDs that can be used for VCPU and PCPU
        allocations.
    """
    if not CONF.vcpu_pin_set:
        return None

    cpuset_ids = parse_cpu_spec(CONF.vcpu_pin_set)
    if not cpuset_ids:
        msg = _("No CPUs available after parsing 'vcpu_pin_set' config, %r")
        raise exception.Invalid(msg % CONF.vcpu_pin_set)
    return cpuset_ids


def get_cpu_dedicated_set():
    """Parse ``[compute] cpu_dedicated_set`` config.

    :returns: A set of host CPU IDs that can be used for PCPU allocations.
    """
    if not CONF.compute.cpu_dedicated_set:
        return None

    cpu_ids = parse_cpu_spec(CONF.compute.cpu_dedicated_set)
    if not cpu_ids:
        msg = _("No CPUs available after parsing '[compute] "
                "cpu_dedicated_set' config, %r")
        raise exception.Invalid(msg % CONF.compute.cpu_dedicated_set)
    return cpu_ids


def get_cpu_shared_set():
    """Parse ``[compute] cpu_shared_set`` config.

    :returns: A set of host CPU IDs that can be used for emulator threads and,
        optionally, for VCPU allocations.
    """
    if not CONF.compute.cpu_shared_set:
        return None

    shared_ids = parse_cpu_spec(CONF.compute.cpu_shared_set)
    if not shared_ids:
        msg = _("No CPUs available after parsing '[compute] cpu_shared_set' "
                "config, %r")
        raise exception.Invalid(msg % CONF.compute.cpu_shared_set)
    return shared_ids


def parse_cpu_spec(spec: str) -> ty.Set[int]:
    """Parse a CPU set specification.

    Each element in the list is either a single CPU number, a range of
    CPU numbers, or a caret followed by a CPU number to be excluded
    from a previous range.

    :param spec: cpu set string eg "1-4,^3,6"

    :returns: a set of CPU indexes
    """
    cpuset_ids: ty.Set[int] = set()
    cpuset_reject_ids: ty.Set[int] = set()
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


def format_cpu_spec(
    cpuset: ty.Set[int],
    allow_ranges: bool = True,
) -> str:
    """Format a libvirt CPU range specification.

    Format a set/list of CPU indexes as a libvirt CPU range
    specification. If allow_ranges is true, it will try to detect
    continuous ranges of CPUs, otherwise it will just list each CPU
    index explicitly.

    :param cpuset: set (or list) of CPU indexes
    :param allow_ranges: Whether we should attempt to detect continuous ranges
        of CPUs.

    :returns: a formatted CPU range string
    """
    # We attempt to detect ranges, but don't bother with
    # trying to do range negations to minimize the overall
    # spec string length
    if allow_ranges:
        ranges: ty.List[ty.List[int]] = []
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

    :raises: exception.ImageSerialPortNumberInvalid if the serial port count
             is not a valid integer
    :raises: exception.ImageSerialPortNumberExceedFlavorValue if the serial
             port count defined in image is greater than that of flavor
    :returns: number of serial ports
    """
    flavor_num_ports, image_num_ports = _get_flavor_image_meta(
        'serial_port_count', flavor, image_meta)
    if flavor_num_ports:
        try:
            flavor_num_ports = int(flavor_num_ports)
        except ValueError:
            raise exception.ImageSerialPortNumberInvalid(
                num_ports=flavor_num_ports)

    if flavor_num_ports and image_num_ports:
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
    if wanttopology.sockets and topology.sockets == wanttopology.sockets:
        score = score + 1
    if wanttopology.cores and topology.cores == wanttopology.cores:
        score = score + 1
    if wanttopology.threads and topology.threads == wanttopology.threads:
        score = score + 1
    return score


def get_cpu_topology_constraints(flavor, image_meta):
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
    :raises: exception.InvalidRequest if one of the provided flavor properties
             is a non-integer
    :returns: A two-tuple of objects.VirtCPUTopology instances. The
              first element corresponds to the preferred topology,
              while the latter corresponds to the maximum topology,
              based on upper limits.
    """
    flavor_max_sockets, image_max_sockets = _get_flavor_image_meta(
        'cpu_max_sockets', flavor, image_meta, 0)
    flavor_max_cores, image_max_cores = _get_flavor_image_meta(
        'cpu_max_cores', flavor, image_meta, 0)
    flavor_max_threads, image_max_threads = _get_flavor_image_meta(
        'cpu_max_threads', flavor, image_meta, 0)
    # image metadata is already of the correct type
    try:
        flavor_max_sockets = int(flavor_max_sockets)
        flavor_max_cores = int(flavor_max_cores)
        flavor_max_threads = int(flavor_max_threads)
    except ValueError as e:
        msg = _('Invalid flavor extra spec. Error: %s') % six.text_type(e)
        raise exception.InvalidRequest(msg)

    LOG.debug("Flavor limits %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": flavor_max_sockets,
               "cores": flavor_max_cores,
               "threads": flavor_max_threads})
    LOG.debug("Image limits %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": image_max_sockets,
               "cores": image_max_cores,
               "threads": image_max_threads})

    # Image limits are not permitted to exceed the flavor
    # limits. ie they can only lower what the flavor defines
    if ((flavor_max_sockets and image_max_sockets > flavor_max_sockets) or
            (flavor_max_cores and image_max_cores > flavor_max_cores) or
            (flavor_max_threads and image_max_threads > flavor_max_threads)):
        raise exception.ImageVCPULimitsRangeExceeded(
            image_sockets=image_max_sockets,
            image_cores=image_max_cores,
            image_threads=image_max_threads,
            flavor_sockets=flavor_max_sockets,
            flavor_cores=flavor_max_cores,
            flavor_threads=flavor_max_threads)

    max_sockets = image_max_sockets or flavor_max_sockets or 65536
    max_cores = image_max_cores or flavor_max_cores or 65536
    max_threads = image_max_threads or flavor_max_threads or 65536

    flavor_sockets, image_sockets = _get_flavor_image_meta(
        'cpu_sockets', flavor, image_meta, 0)
    flavor_cores, image_cores = _get_flavor_image_meta(
        'cpu_cores', flavor, image_meta, 0)
    flavor_threads, image_threads = _get_flavor_image_meta(
        'cpu_threads', flavor, image_meta, 0)
    try:
        flavor_sockets = int(flavor_sockets)
        flavor_cores = int(flavor_cores)
        flavor_threads = int(flavor_threads)
    except ValueError as e:
        msg = _('Invalid flavor extra spec. Error: %s') % six.text_type(e)
        raise exception.InvalidRequest(msg)

    LOG.debug("Flavor pref %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": flavor_sockets,
               "cores": flavor_cores,
               "threads": flavor_threads})
    LOG.debug("Image pref %(sockets)d:%(cores)d:%(threads)d",
              {"sockets": image_sockets,
               "cores": image_cores,
               "threads": image_threads})

    # If the image limits have reduced the flavor limits we might need
    # to discard the preferred topology from the flavor
    if ((flavor_sockets > max_sockets) or
            (flavor_cores > max_cores) or
            (flavor_threads > max_threads)):
        flavor_sockets = flavor_cores = flavor_threads = 0

    # However, image topology is not permitted to exceed image/flavor
    # limits
    if ((image_sockets > max_sockets) or
            (image_cores > max_cores) or
            (image_threads > max_threads)):
        raise exception.ImageVCPUTopologyRangeExceeded(
            image_sockets=image_sockets,
            image_cores=image_cores,
            image_threads=image_threads,
            max_sockets=max_sockets,
            max_cores=max_cores,
            max_threads=max_threads)

    # If no preferred topology was set against the image then use the
    # preferred topology from the flavor. We use 'not or' rather than
    # 'not and', since if any value is set against the image this
    # invalidates the entire set of values from the flavor
    if not any((image_sockets, image_cores, image_threads)):
        sockets = flavor_sockets
        cores = flavor_cores
        threads = flavor_threads
    else:
        sockets = image_sockets
        cores = image_cores
        threads = image_threads

    LOG.debug('Chose sockets=%(sockets)d, cores=%(cores)d, '
              'threads=%(threads)d; limits were sockets=%(maxsockets)d, '
              'cores=%(maxcores)d, threads=%(maxthreads)d',
              {"sockets": sockets, "cores": cores,
               "threads": threads, "maxsockets": max_sockets,
               "maxcores": max_cores, "maxthreads": max_threads})

    return (objects.VirtCPUTopology(sockets=sockets, cores=cores,
                                    threads=threads),
            objects.VirtCPUTopology(sockets=max_sockets, cores=max_cores,
                                    threads=max_threads))


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
    scores: ty.Dict[int, ty.List['objects.VirtCPUTopology']] = (
        collections.defaultdict(list)
    )
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

    preferred, maximum = get_cpu_topology_constraints(flavor, image_meta)
    LOG.debug("Topology preferred %(preferred)s, maximum %(maximum)s",
              {"preferred": preferred, "maximum": maximum})

    possible = _get_possible_cpu_topologies(flavor.vcpus,
                                            maximum,
                                            allow_threads)
    LOG.debug("Possible topologies %s", possible)

    if numa_topology:
        min_requested_threads = None
        cell_topologies = [cell.cpu_topology for cell in numa_topology.cells
                           if ('cpu_topology' in cell and cell.cpu_topology)]
        if cell_topologies:
            min_requested_threads = min(
                    topo.threads for topo in cell_topologies)

        if min_requested_threads:
            if preferred.threads:
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
            if host_cell.can_fit_pagesize(pagesize, inst_cell_mem):
                return pagesize

    if inst_cell.pagesize == MEMPAGES_SMALL:
        return verify_pagesizes(host_cell, inst_cell, avail_pagesize[-1:])
    elif inst_cell.pagesize == MEMPAGES_LARGE:
        return verify_pagesizes(host_cell, inst_cell, avail_pagesize[:-1])
    elif inst_cell.pagesize == MEMPAGES_ANY:
        return verify_pagesizes(host_cell, inst_cell, avail_pagesize)
    else:
        return verify_pagesizes(host_cell, inst_cell, [inst_cell.pagesize])


def _pack_instance_onto_cores(host_cell, instance_cell,
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

    :param host_cell: objects.NUMACell instance - the host cell that
                      the instance should be pinned to
    :param instance_cell: An instance of objects.InstanceNUMACell
                          describing the pinning requirements of the
                          instance
    :param num_cpu_reserved: number of pCPUs reserved for hypervisor

    :returns: An instance of objects.InstanceNUMACell containing the
              pinning information, the physical cores reserved and
              potentially a new topology to be exposed to the
              instance. None if there is no valid way to satisfy the
              sibling requirements for the instance.
    """
    # get number of threads per core in host's cell
    threads_per_core = max(map(len, host_cell.siblings)) or 1

    LOG.debug('Packing an instance onto a set of siblings: '
             '    host_cell_free_siblings: %(siblings)s'
             '    instance_cell: %(cells)s'
             '    host_cell_id: %(host_cell_id)s'
             '    threads_per_core: %(threads_per_core)s'
             '    num_cpu_reserved: %(num_cpu_reserved)s',
                {'siblings': host_cell.free_siblings,
                 'cells': instance_cell,
                 'host_cell_id': host_cell.id,
                 'threads_per_core': threads_per_core,
                 'num_cpu_reserved': num_cpu_reserved})

    # We build up a data structure that answers the question: 'Given the
    # number of threads I want to pack, give me a list of all the available
    # sibling sets (or groups thereof) that can accommodate it'
    sibling_sets: ty.Dict[int, ty.List[ty.Set[int]]] = (
        collections.defaultdict(list)
    )
    for sib in host_cell.free_siblings:
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
        return math.gcd(threads_per_core, _orphans(instance_cell,
                                                   threads_per_core))

    def _get_pinning(threads_no, sibling_set, instance_cores):
        """Determines pCPUs/vCPUs mapping

        Determines the pCPUs/vCPUs mapping regarding the number of
        threads which can be used per cores.

        :param threads_no: Number of host threads per cores which can
                           be used to pin vCPUs according to the
                           policies.
        :param sibling_set: List of available threads per host cores
                            on a specific host NUMA node.
        :param instance_cores: Set of vCPUs requested.

        NOTE: Depending on how host is configured (HT/non-HT) a thread can
              be considered as an entire core.
        """
        if threads_no * len(sibling_set) < (len(instance_cores)):
            return None

        # Determines usable cores according the "threads number"
        # constraint.
        #
        # For a sibling_set=[(0, 1, 2, 3), (4, 5, 6, 7)] and thread_no 1:
        # usable_cores=[[0], [4]]
        #
        # For a sibling_set=[(0, 1, 2, 3), (4, 5, 6, 7)] and thread_no 2:
        # usable_cores=[[0, 1], [4, 5]]
        usable_cores = list(map(lambda s: list(s)[:threads_no], sibling_set))

        # Determines the mapping vCPUs/pCPUs based on the sets of
        # usable cores.
        #
        # For an instance_cores=[2, 3], usable_cores=[[0], [4]]
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

        return vcpus_pinning

    def _get_reserved(sibling_set, vcpus_pinning, num_cpu_reserved=0,
                      cpu_thread_isolate=False):
        """Given available sibling_set, returns the pCPUs reserved
        for hypervisor.

        :param sibling_set: List of available threads per host cores
                            on a specific host NUMA node.
        :param vcpus_pinning: List of tuple of (pCPU, vCPU) mapping.
        :param num_cpu_reserved: Number of additional host CPUs which
                                 need to be reserved.
        :param cpu_thread_isolate: True if CPUThreadAllocationPolicy
                                   is ISOLATE.
        """
        if not vcpus_pinning:
            return None

        cpuset_reserved = None
        usable_cores = list(map(lambda s: list(s), sibling_set))

        if num_cpu_reserved:
            # Updates the pCPUs used based on vCPUs pinned to.
            # For the case vcpus_pinning=[(0, 0), (1, 2)] and
            # usable_cores=[[0, 1], [2, 3], [4, 5]],
            # if CPUThreadAllocationPolicy is isolated, we want
            # to update usable_cores=[[4, 5]].
            # If CPUThreadAllocationPolicy is *not* isolated,
            # we want to update usable_cores=[[1],[3],[4, 5]].
            for vcpu, pcpu in vcpus_pinning:
                for sib in usable_cores:
                    if pcpu in sib:
                        if cpu_thread_isolate:
                            usable_cores.remove(sib)
                        else:
                            sib.remove(pcpu)

            # Determines the pCPUs reserved for hypervisor
            #
            # For usable_cores=[[1],[3],[4, 5]], num_cpu_reserved=1
            # cpuset_reserved=set([1])
            cpuset_reserved = set(list(
                itertools.chain(*usable_cores))[:num_cpu_reserved])
            msg = ("Computed NUMA topology reserved pCPUs: usable pCPUs: "
                   "%(usable_cores)s, reserved pCPUs: %(cpuset_reserved)s")
            msg_args = {
                'usable_cores': usable_cores,
                'cpuset_reserved': cpuset_reserved,
            }
            LOG.info(msg, msg_args)

        return cpuset_reserved or None

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

        # TODO(stephenfin): Drop this when we drop support for 'vcpu_pin_set'
        # NOTE(stephenfin): This is total hack. We're relying on the fact that
        # the libvirt driver, which is the only one that currently supports
        # pinned CPUs, will set cpuset and pcpuset to the same value if using
        # legacy configuration, i.e. 'vcpu_pin_set', as part of
        # '_get_host_numa_topology'. They can't be equal otherwise since
        # 'cpu_dedicated_set' and 'cpu_shared_set' must be disjoint. Therefore,
        # if these are equal, the host that this NUMA cell corresponds to is
        # using legacy configuration and it's okay to use the old, "pin a core
        # and reserve its siblings" implementation of the 'isolate' policy. If
        # they're not, the host is using new-style configuration and we've just
        # hit bug #1889633
        if threads_per_core != 1 and host_cell.pcpuset != host_cell.cpuset:
            LOG.warning(
                "Host supports hyperthreads, but instance requested no "
                "hyperthreads. This should have been rejected by the "
                "scheduler but we likely got here due to the fallback VCPU "
                "query. Consider setting '[workarounds] "
                "disable_fallback_pcpu_query' to 'True' once hosts are no "
                "longer using 'vcpu_pin_set'. Refer to bug #1889633 for more "
                "information."
            )
            return

        pinning = _get_pinning(
            1,  # we only want to "use" one thread per core
            sibling_sets[threads_per_core],
            instance_cell.pcpuset)
        cpuset_reserved = _get_reserved(
            sibling_sets[1], pinning, num_cpu_reserved=num_cpu_reserved,
            cpu_thread_isolate=True)
        if not pinning or (num_cpu_reserved and not cpuset_reserved):
            pinning, cpuset_reserved = (None, None)

    else:  # REQUIRE, PREFER (explicit, implicit)
        if (instance_cell.cpu_thread_policy ==
                fields.CPUThreadAllocationPolicy.REQUIRE):
            # make sure we actually have some siblings to play with
            if threads_per_core <= 1:
                LOG.info("Host does not support hyperthreading or "
                         "hyperthreading is disabled, but 'require' "
                         "threads policy was requested.")
                return

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

            pinning = _get_pinning(
                threads_no, sibling_set,
                instance_cell.pcpuset)
            cpuset_reserved = _get_reserved(
                sibling_sets[1], pinning, num_cpu_reserved=num_cpu_reserved)
            if not pinning or (num_cpu_reserved and not cpuset_reserved):
                continue
            break

        # NOTE(sfinucan): If siblings weren't available and we're using PREFER
        # (implicitly or explicitly), fall back to linear assignment across
        # cores
        if (instance_cell.cpu_thread_policy !=
                fields.CPUThreadAllocationPolicy.REQUIRE and
                not pinning):
            threads_no = 1
            # we create a fake sibling set by splitting all sibling sets and
            # treating each core as if it has no siblings. This is necessary
            # because '_get_pinning' will normally only take the same amount of
            # cores ('threads_no' cores) from each sibling set. This is rather
            # desirable when we're seeking to apply a thread policy but it is
            # less desirable when we only care about resource usage as we do
            # here. By treating each core as independent, as we do here, we
            # maximize resource usage for almost-full nodes at the expense of a
            # possible performance impact to the guest.
            sibling_set = [set([x]) for x in itertools.chain(*sibling_sets[1])]
            pinning = _get_pinning(
                threads_no, sibling_set,
                instance_cell.pcpuset)
            cpuset_reserved = _get_reserved(
                sibling_set, pinning, num_cpu_reserved=num_cpu_reserved)

        threads_no = _threads(instance_cell, threads_no)

    if not pinning or (num_cpu_reserved and not cpuset_reserved):
        return
    LOG.debug('Selected cores for pinning: %s, in cell %s', pinning,
                                                            host_cell.id)

    topology = objects.VirtCPUTopology(sockets=1,
                                       cores=len(pinning) // threads_no,
                                       threads=threads_no)
    instance_cell.pin_vcpus(*pinning)
    instance_cell.cpu_topology = topology
    instance_cell.id = host_cell.id
    instance_cell.cpuset_reserved = cpuset_reserved
    return instance_cell


def _numa_fit_instance_cell(
    host_cell: 'objects.NUMACell',
    instance_cell: 'objects.InstanceNUMACell',
    limits: ty.Optional['objects.NUMATopologyLimit'] = None,
    cpuset_reserved: int = 0,
) -> ty.Optional['objects.InstanceNUMACell']:
    """Ensure an instance cell can fit onto a host cell

    Ensure an instance cell can fit onto a host cell and, if so, return
    a new objects.InstanceNUMACell with the id set to that of the host.
    Returns None if the instance cell exceeds the limits of the host.

    :param host_cell: host cell to fit the instance cell onto
    :param instance_cell: instance cell we want to fit
    :param limits: an objects.NUMATopologyLimit or None
    :param cpuset_reserved: An int to indicate the number of CPUs overhead

    :returns: objects.InstanceNUMACell with the id set to that of the
              host, or None
    """
    LOG.debug('Attempting to fit instance cell %(cell)s on host_cell '
              '%(host_cell)s', {'cell': instance_cell, 'host_cell': host_cell})

    if 'pagesize' in instance_cell and instance_cell.pagesize:
        # The instance has requested a page size.  Verify that the requested
        # size is valid and that there are available pages of that size on the
        # host.
        pagesize = _numa_cell_supports_pagesize_request(
            host_cell, instance_cell)
        if not pagesize:
            LOG.debug('Host does not support requested memory pagesize, '
                      'or not enough free pages of the requested size. '
                      'Requested: %d kB', instance_cell.pagesize)
            return None
        LOG.debug('Selected memory pagesize: %(selected_mem_pagesize)d kB. '
                  'Requested memory pagesize: %(requested_mem_pagesize)d '
                  '(small = -1, large = -2, any = -3)',
                  {'selected_mem_pagesize': pagesize,
                   'requested_mem_pagesize': instance_cell.pagesize})
        instance_cell.pagesize = pagesize
    else:
        # The instance provides a NUMA topology but does not define any
        # particular page size for its memory.
        if host_cell.mempages:
            # The host supports explicit page sizes. Use a pagesize-aware
            # memory check using the smallest available page size.
            pagesize = _get_smallest_pagesize(host_cell)
            LOG.debug('No specific pagesize requested for instance, '
                      'selected pagesize: %d', pagesize)
            # we want to allow overcommit in this case as we're not using
            # hugepages
            if not host_cell.can_fit_pagesize(pagesize,
                                              instance_cell.memory * units.Ki,
                                              use_free=False):
                LOG.debug('Not enough available memory to schedule instance '
                          'with pagesize %(pagesize)d. Required: '
                          '%(required)s, available: %(available)s, total: '
                          '%(total)s.',
                          {'required': instance_cell.memory,
                           'available': host_cell.avail_memory,
                           'total': host_cell.memory,
                           'pagesize': pagesize})
                return None
        else:
            # The host does not support explicit page sizes. Ignore pagesizes
            # completely.
            # NOTE(stephenfin): Do not allow an instance to overcommit against
            # itself on any NUMA cell, i.e. with 'ram_allocation_ratio = 2.0'
            # on a host with 1GB RAM, we should allow two 1GB instances but not
            # one 2GB instance.
            if instance_cell.memory > host_cell.memory:
                LOG.debug('Not enough host cell memory to fit instance cell. '
                          'Required: %(required)d, actual: %(actual)d',
                          {'required': instance_cell.memory,
                           'actual': host_cell.memory})
                return None

    # NOTE(stephenfin): As with memory, do not allow an instance to overcommit
    # against itself on any NUMA cell
    if instance_cell.cpu_policy in (
        fields.CPUAllocationPolicy.DEDICATED,
        fields.CPUAllocationPolicy.MIXED,
    ):
        required_cpus = len(instance_cell.pcpuset) + cpuset_reserved
        if required_cpus > len(host_cell.pcpuset):
            LOG.debug('Not enough host cell CPUs to fit instance cell; '
                      'required: %(required)d + %(cpuset_reserved)d as '
                      'overhead, actual: %(actual)d', {
                          'required': len(instance_cell.pcpuset),
                          'actual': len(host_cell.pcpuset),
                          'cpuset_reserved': cpuset_reserved
                      })
            return None
    else:
        required_cpus = len(instance_cell.cpuset)
        if required_cpus > len(host_cell.cpuset):
            LOG.debug('Not enough host cell CPUs to fit instance cell; '
                      'required: %(required)d, actual: %(actual)d', {
                          'required': len(instance_cell.cpuset),
                          'actual': len(host_cell.cpuset),
                      })
            return None

    if instance_cell.cpu_policy in (
        fields.CPUAllocationPolicy.DEDICATED,
        fields.CPUAllocationPolicy.MIXED,
    ):
        LOG.debug('Pinning has been requested')
        required_cpus = len(instance_cell.pcpuset) + cpuset_reserved
        if required_cpus > host_cell.avail_pcpus:
            LOG.debug('Not enough available CPUs to schedule instance. '
                      'Oversubscription is not possible with pinned '
                      'instances. Required: %(required)d (%(vcpus)d + '
                      '%(num_cpu_reserved)d), actual: %(actual)d',
                      {'required': required_cpus,
                       'vcpus': len(instance_cell.pcpuset),
                       'actual': host_cell.avail_pcpus,
                       'num_cpu_reserved': cpuset_reserved})
            return None

        if instance_cell.memory > host_cell.avail_memory:
            LOG.debug('Not enough available memory to schedule instance. '
                      'Oversubscription is not possible with pinned '
                      'instances. Required: %(required)s, available: '
                      '%(available)s, total: %(total)s. ',
                      {'required': instance_cell.memory,
                       'available': host_cell.avail_memory,
                       'total': host_cell.memory})
            return None

        # Try to pack the instance cell onto cores
        instance_cell = _pack_instance_onto_cores(
            host_cell, instance_cell, num_cpu_reserved=cpuset_reserved,
        )
        if not instance_cell:
            LOG.debug('Failed to map instance cell CPUs to host cell CPUs')
            return None

    elif limits:
        LOG.debug('No pinning requested, considering limitations on usable cpu'
                  ' and memory')
        cpu_usage = host_cell.cpu_usage + len(instance_cell.cpuset)
        cpu_limit = len(host_cell.cpuset) * limits.cpu_allocation_ratio
        if cpu_usage > cpu_limit:
            LOG.debug('Host cell has limitations on usable CPUs. There are '
                      'not enough free CPUs to schedule this instance. '
                      'Usage: %(usage)d, limit: %(limit)d',
                      {'usage': cpu_usage, 'limit': cpu_limit})
            return None

        ram_usage = host_cell.memory_usage + instance_cell.memory
        ram_limit = host_cell.memory * limits.ram_allocation_ratio
        if ram_usage > ram_limit:
            LOG.debug('Host cell has limitations on usable memory. There is '
                      'not enough free memory to schedule this instance. '
                      'Usage: %(usage)d, limit: %(limit)d',
                      {'usage': ram_usage, 'limit': ram_limit})
            return None

    instance_cell.id = host_cell.id
    return instance_cell


def _get_flavor_image_meta(
    key: str,
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
    default: ty.Any = None,
) -> ty.Tuple[ty.Any, ty.Any]:
    """Extract both flavor- and image-based variants of metadata."""
    flavor_key = ':'.join(['hw', key])
    image_key = '_'.join(['hw', key])

    flavor_value = flavor.get('extra_specs', {}).get(flavor_key, default)
    image_value = image_meta.properties.get(image_key, default)

    return flavor_value, image_value


def _get_unique_flavor_image_meta(
    key: str,
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
    default: ty.Any = None
) -> ty.Any:
    """A variant of '_get_flavor_image_meta' that errors out on conflicts."""
    flavor_value, image_value = _get_flavor_image_meta(
        key, flavor, image_meta, default,
    )
    if image_value and flavor_value and image_value != flavor_value:
        msg = _(
            "Flavor %(flavor_name)s has hw:%(key)s extra spec explicitly "
            "set to %(flavor_val)s, conflicting with image %(image_name)s "
            "which has hw_%(key)s explicitly set to %(image_val)s."
        )
        raise exception.FlavorImageConflict(
            msg % {
                'key': key,
                'flavor_name': flavor.name,
                'flavor_val': flavor_value,
                'image_name': image_meta.name,
                'image_val': image_value,
            },
        )

    return flavor_value or image_value


def get_mem_encryption_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
    machine_type: ty.Optional[str] = None,
) -> bool:
    """Return a boolean indicating whether encryption of guest memory was
    requested, either via the hw:mem_encryption extra spec or the
    hw_mem_encryption image property (or both).

    Also watch out for contradictory requests between the flavor and
    image regarding memory encryption, and raise an exception where
    encountered.  These conflicts can arise in two different ways:

        1) the flavor requests memory encryption but the image
           explicitly requests *not* to have memory encryption, or
           vice-versa

        2) the flavor and/or image request memory encryption, but the
           image is missing hw_firmware_type=uefi

        3) the flavor and/or image request memory encryption, but the
           machine type is set to a value which does not contain 'q35'

    This can be called from the libvirt driver on the compute node, in
    which case the driver should pass the result of
    nova.virt.libvirt.utils.get_machine_type() as the machine_type
    parameter, or from the API layer, in which case get_machine_type()
    cannot be called since it relies on being run from the compute
    node in order to retrieve CONF.libvirt.hw_machine_type.

    :param instance_type: Flavor object
    :param image: an ImageMeta object
    :param machine_type: a string representing the machine type (optional)
    :raises: nova.exception.FlavorImageConflict
    :raises: nova.exception.InvalidMachineType
    :returns: boolean indicating whether encryption of guest memory
    was requested
    """

    flavor_mem_enc_str, image_mem_enc = _get_flavor_image_meta(
        'mem_encryption', flavor, image_meta)

    flavor_mem_enc = None
    if flavor_mem_enc_str is not None:
        flavor_mem_enc = strutils.bool_from_string(flavor_mem_enc_str)

    # Image property is a FlexibleBooleanField, so coercion to a
    # boolean is handled automatically

    if not flavor_mem_enc and not image_mem_enc:
        return False

    _check_for_mem_encryption_requirement_conflicts(
        flavor_mem_enc_str, flavor_mem_enc, image_mem_enc, flavor, image_meta)

    # If we get this far, either the extra spec or image property explicitly
    # specified a requirement regarding memory encryption, and if both did,
    # they are asking for the same thing.
    requesters = []
    if flavor_mem_enc:
        requesters.append("hw:mem_encryption extra spec in %s flavor" %
                          flavor.name)
    if image_mem_enc:
        requesters.append("hw_mem_encryption property of image %s" %
                          image_meta.name)

    _check_mem_encryption_uses_uefi_image(requesters, image_meta)
    _check_mem_encryption_machine_type(image_meta, machine_type)

    LOG.debug("Memory encryption requested by %s", " and ".join(requesters))
    return True


def _check_for_mem_encryption_requirement_conflicts(
        flavor_mem_enc_str, flavor_mem_enc, image_mem_enc, flavor, image_meta):
    # Check for conflicts between explicit requirements regarding
    # memory encryption.
    if (flavor_mem_enc is not None and image_mem_enc is not None and
            flavor_mem_enc != image_mem_enc):
        emsg = _(
            "Flavor %(flavor_name)s has hw:mem_encryption extra spec "
            "explicitly set to %(flavor_val)s, conflicting with "
            "image %(image_name)s which has hw_mem_encryption property "
            "explicitly set to %(image_val)s"
        )
        data = {
            'flavor_name': flavor.name,
            'flavor_val': flavor_mem_enc_str,
            'image_name': image_meta.name,
            'image_val': image_mem_enc,
        }
        raise exception.FlavorImageConflict(emsg % data)


def _check_mem_encryption_uses_uefi_image(requesters, image_meta):
    if image_meta.properties.get('hw_firmware_type') == 'uefi':
        return

    emsg = _(
        "Memory encryption requested by %(requesters)s but image "
        "%(image_name)s doesn't have 'hw_firmware_type' property set to 'uefi'"
    )
    data = {'requesters': " and ".join(requesters),
            'image_name': image_meta.name}
    raise exception.FlavorImageConflict(emsg % data)


def _check_mem_encryption_machine_type(image_meta, machine_type=None):
    # NOTE(aspiers): As explained in the SEV spec, SEV needs a q35
    # machine type in order to bind all the virtio devices to the PCIe
    # bridge so that they use virtio 1.0 and not virtio 0.9, since
    # QEMU's iommu_platform feature was added in virtio 1.0 only:
    #
    # http://specs.openstack.org/openstack/nova-specs/specs/train/approved/amd-sev-libvirt-support.html
    #
    # So if the image explicitly requests a machine type which is not
    # in the q35 family, raise an exception.
    #
    # This check can be triggered both at API-level, at which point we
    # can't check here what value of CONF.libvirt.hw_machine_type may
    # have been configured on the compute node, and by the libvirt
    # driver, in which case the driver can check that config option
    # and will pass the machine_type parameter.
    mach_type = machine_type or image_meta.properties.get('hw_machine_type')

    # If hw_machine_type is not specified on the image and is not
    # configured correctly on SEV compute nodes, then a separate check
    # in the driver will catch that and potentially retry on other
    # compute nodes.
    if mach_type is None:
        return

    # Could be something like pc-q35-2.11 if a specific version of the
    # machine type is required, so do substring matching.
    if 'q35' not in mach_type:
        raise exception.InvalidMachineType(
            mtype=mach_type,
            image_id=image_meta.id, image_name=image_meta.name,
            reason=_("q35 type is required for SEV to work"))


def _get_numa_pagesize_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[int]:
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
        elif request.isdigit():
            return int(request)

        try:
            return strutils.string_to_bytes(
                request, return_int=True) / units.Ki
        except ValueError:
            raise exception.MemoryPageSizeInvalid(pagesize=request) from None

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


def _get_constraint_mappings_from_flavor(flavor, key, func):
    hw_numa_map = []
    extra_specs = flavor.get('extra_specs', {})
    for cellid in range(objects.ImageMetaProps.NUMA_NODES_MAX):
        prop = '%s.%d' % (key, cellid)
        if prop not in extra_specs:
            break
        hw_numa_map.append(func(extra_specs[prop]))

    return hw_numa_map or None


def _get_numa_cpu_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[ty.List[ty.Set[int]]]:
    """Validate and return the requested guest NUMA-guest CPU mapping.

    Extract the user-provided mapping of guest CPUs to guest NUMA nodes. For
    example, the flavor extra spec ``hw:numa_cpus.0=0-1,4`` will map guest
    cores ``0``, ``1``, ``4`` to guest NUMA node ``0``.

    :param flavor: ``nova.objects.Flavor`` instance
    :param image_meta: ``nova.objects.ImageMeta`` instance
    :raises: exception.ImageNUMATopologyForbidden if both image metadata and
        flavor extra specs are defined.
    :return: An ordered list of sets of CPU indexes to assign to each guest
        NUMA node if matching extra specs or image metadata properties found,
        else None.
    """
    flavor_cpu_list = _get_constraint_mappings_from_flavor(
        flavor, 'hw:numa_cpus', parse_cpu_spec)
    image_cpu_list = image_meta.properties.get('hw_numa_cpus', None)

    if flavor_cpu_list is None:
        return image_cpu_list

    if image_cpu_list is not None:
        raise exception.ImageNUMATopologyForbidden(
            name='hw_numa_cpus')

    return flavor_cpu_list


def _get_numa_mem_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[ty.List[int]]:
    """Validate and return the requested guest NUMA-guest memory mapping.

    Extract the user-provided mapping of guest memory to guest NUMA nodes. For
    example, the flavor extra spec ``hw:numa_mem.0=1`` will map 1 GB of guest
    memory to guest NUMA node ``0``.

    :param flavor: ``nova.objects.Flavor`` instance
    :param image_meta: ``nova.objects.ImageMeta`` instance
    :raises: exception.ImageNUMATopologyForbidden if both image metadata and
        flavor extra specs are defined
    :return: An ordered list of memory (in GB) to assign to each guest NUMA
        node if matching extra specs or image metadata properties found, else
        None.
    """
    flavor_mem_list = _get_constraint_mappings_from_flavor(
        flavor, 'hw:numa_mem', int)
    image_mem_list = image_meta.properties.get('hw_numa_mem', None)

    if flavor_mem_list is None:
        return image_mem_list

    if image_mem_list is not None:
        raise exception.ImageNUMATopologyForbidden(
            name='hw_numa_mem')

    return flavor_mem_list


def _get_numa_node_count_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[int]:
    """Validate and return the requested NUMA nodes.

    :param flavor: ``nova.objects.Flavor`` instance
    :param image_meta: ``nova.objects.ImageMeta`` instance
    :raises: exception.ImageNUMATopologyForbidden if both image metadata and
        flavor extra specs are defined
    :raises: exception.InvalidNUMANodesNumber if the number of NUMA
        nodes is less than 1 or not an integer
    :returns: The number of NUMA nodes requested in either the flavor or image,
        else None.
    """
    flavor_nodes, image_nodes = _get_flavor_image_meta(
        'numa_nodes', flavor, image_meta)
    if flavor_nodes and image_nodes:
        raise exception.ImageNUMATopologyForbidden(name='hw_numa_nodes')

    nodes = flavor_nodes or image_nodes
    if nodes is not None and (not strutils.is_int_like(nodes) or
            int(nodes) < 1):
        raise exception.InvalidNUMANodesNumber(nodes=nodes)

    return int(nodes) if nodes else nodes


# NOTE(stephenfin): This must be public as it's used elsewhere
def get_cpu_policy_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[str]:
    """Validate and return the requested CPU policy.

    :param flavor: ``nova.objects.Flavor`` instance
    :param image_meta: ``nova.objects.ImageMeta`` instance
    :raises: exception.ImageCPUPinningForbidden if policy is defined on both
        image and flavor and these policies conflict.
    :raises: exception.InvalidCPUAllocationPolicy if policy is defined with
        invalid value in image or flavor.
    :returns: The CPU policy requested.
    """
    flavor_policy, image_policy = _get_flavor_image_meta(
        'cpu_policy', flavor, image_meta)

    if flavor_policy and (flavor_policy not in fields.CPUAllocationPolicy.ALL):
        raise exception.InvalidCPUAllocationPolicy(
            source='flavor extra specs',
            requested=flavor_policy,
            available=str(fields.CPUAllocationPolicy.ALL))

    if image_policy and (image_policy not in fields.CPUAllocationPolicy.ALL):
        raise exception.InvalidCPUAllocationPolicy(
            source='image properties',
            requested=image_policy,
            available=str(fields.CPUAllocationPolicy.ALL))

    if flavor_policy == fields.CPUAllocationPolicy.DEDICATED:
        cpu_policy = flavor_policy
    elif flavor_policy == fields.CPUAllocationPolicy.MIXED:
        if image_policy == fields.CPUAllocationPolicy.DEDICATED:
            raise exception.ImageCPUPinningForbidden()
        cpu_policy = flavor_policy
    elif flavor_policy == fields.CPUAllocationPolicy.SHARED:
        if image_policy in (
            fields.CPUAllocationPolicy.MIXED,
            fields.CPUAllocationPolicy.DEDICATED,
        ):
            raise exception.ImageCPUPinningForbidden()
        cpu_policy = flavor_policy
    elif image_policy in fields.CPUAllocationPolicy.ALL:
        cpu_policy = image_policy
    else:
        cpu_policy = None

    return cpu_policy


# NOTE(stephenfin): This must be public as it's used elsewhere
def get_cpu_thread_policy_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[str]:
    """Validate and return the requested CPU thread policy.

    :param flavor: ``nova.objects.Flavor`` instance
    :param image_meta: ``nova.objects.ImageMeta`` instance
    :raises: exception.ImageCPUThreadPolicyForbidden if policy is defined on
        both image and flavor and these policies conflict.
    :raises: exception.InvalidCPUThreadAllocationPolicy if policy is defined
        with invalid value in image or flavor.
    :returns: The CPU thread policy requested.
    """
    flavor_policy, image_policy = _get_flavor_image_meta(
        'cpu_thread_policy', flavor, image_meta)

    if flavor_policy and (
            flavor_policy not in fields.CPUThreadAllocationPolicy.ALL):
        raise exception.InvalidCPUThreadAllocationPolicy(
            source='flavor extra specs',
            requested=flavor_policy,
            available=str(fields.CPUThreadAllocationPolicy.ALL))

    if image_policy and (
            image_policy not in fields.CPUThreadAllocationPolicy.ALL):
        raise exception.InvalidCPUThreadAllocationPolicy(
            source='image properties',
            requested=image_policy,
            available=str(fields.CPUThreadAllocationPolicy.ALL))

    if flavor_policy in [None, fields.CPUThreadAllocationPolicy.PREFER]:
        policy = flavor_policy or image_policy
    elif image_policy and image_policy != flavor_policy:
        raise exception.ImageCPUThreadPolicyForbidden()
    else:
        policy = flavor_policy

    return policy


def _get_numa_topology_auto(
    nodes: int,
    flavor: 'objects.Flavor',
    vcpus: ty.Set[int],
    pcpus: ty.Set[int],
) -> 'objects.InstanceNUMATopology':
    """Generate a NUMA topology automatically based on CPUs and memory.

    This is "automatic" because there's no user-provided per-node configuration
    here - it's all auto-generated based on the number of nodes.

    :param nodes: The number of nodes required in the generated topology.
    :param flavor: The flavor used for the instance, from which to extract the
        CPU and memory count.
    :param vcpus: A set of IDs for CPUs that should be shared.
    :param pcpus: A set of IDs for CPUs that should be dedicated.
    """
    if (flavor.vcpus % nodes) > 0 or (flavor.memory_mb % nodes) > 0:
        raise exception.ImageNUMATopologyAsymmetric()

    cells = []
    for node in range(nodes):
        ncpus = int(flavor.vcpus / nodes)
        mem = int(flavor.memory_mb / nodes)
        start = node * ncpus
        cpus = set(range(start, start + ncpus))

        cells.append(objects.InstanceNUMACell(
            id=node, cpuset=cpus & vcpus, pcpuset=cpus & pcpus, memory=mem))

    return objects.InstanceNUMATopology(cells=cells)


def _get_numa_topology_manual(
    nodes: int,
    flavor: 'objects.Flavor',
    vcpus: ty.Set[int],
    pcpus: ty.Set[int],
    cpu_list: ty.List[ty.Set[int]],
    mem_list: ty.List[int],
) -> 'objects.InstanceNUMATopology':
    """Generate a NUMA topology based on user-provided NUMA topology hints.

    :param nodes: The number of nodes required in the generated topology.
    :param flavor: The flavor used for the instance, from which to extract the
        CPU and memory count.
    :param vcpus: A set of IDs for CPUs that should be shared.
    :param pcpus: A set of IDs for CPUs that should be dedicated.
    :param cpu_list: A list of sets of ints; each set in the list corresponds
        to the set of guest cores to assign to NUMA node $index.
    :param mem_list: A list of ints; each int corresponds to the amount of
        memory to assign to NUMA node $index.
    :returns: The generated instance NUMA topology.
    """
    cells = []
    totalmem = 0

    availcpus = set(range(flavor.vcpus))

    for node in range(nodes):
        mem = mem_list[node]
        cpus = cpu_list[node]

        for cpu in cpus:
            if cpu > (flavor.vcpus - 1):
                raise exception.ImageNUMATopologyCPUOutOfRange(
                    cpunum=cpu, cpumax=(flavor.vcpus - 1))

            if cpu not in availcpus:
                raise exception.ImageNUMATopologyCPUDuplicates(
                    cpunum=cpu)

            availcpus.remove(cpu)

        cells.append(objects.InstanceNUMACell(
            id=node, cpuset=cpus & vcpus, pcpuset=cpus & pcpus, memory=mem))
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


def _get_vcpu_pcpu_resources(
    flavor: 'objects.Flavor',
) -> ty.Tuple[int, int]:
    requested_vcpu = 0
    requested_pcpu = 0

    for key, val in flavor.get('extra_specs', {}).items():
        if re.match('resources([1-9][0-9]*)?:%s' % orc.VCPU, key):
            try:
                requested_vcpu += int(val)
            except ValueError:
                # this is handled elsewhere
                pass
        if re.match('resources([1-9][0-9]*)?:%s' % orc.PCPU, key):
            try:
                requested_pcpu += int(val)
            except ValueError:
                # this is handled elsewhere
                pass

    return requested_vcpu, requested_pcpu


def _get_hyperthreading_trait(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[str]:
    for key, val in flavor.get('extra_specs', {}).items():
        if re.match('trait([1-9][0-9]*)?:%s' % os_traits.HW_CPU_HYPERTHREADING,
                    key):
            return val

    if os_traits.HW_CPU_HYPERTHREADING in image_meta.properties.get(
            'traits_required', []):
        return 'required'

    return None


# NOTE(stephenfin): This must be public as it's used elsewhere
def get_dedicated_cpu_constraint(
    flavor: 'objects.Flavor',
) -> ty.Optional[ty.Set[int]]:
    """Validate and return the requested dedicated CPU mask.

    :param flavor: ``nova.objects.Flavor`` instance
    :returns: The dedicated CPUs requested, else None.
    """
    mask = flavor.get('extra_specs', {}).get('hw:cpu_dedicated_mask')
    if not mask:
        return None

    if mask.strip().startswith('^'):
        pcpus = parse_cpu_spec("0-%d,%s" % (flavor.vcpus - 1, mask))
    else:
        pcpus = parse_cpu_spec("%s" % (mask))

    cpus = set(range(flavor.vcpus))
    vcpus = cpus - pcpus
    if not pcpus or not vcpus:
        raise exception.InvalidMixedInstanceDedicatedMask()

    if not pcpus.issubset(cpus):
        msg = _('Mixed instance dedicated vCPU(s) mask is not a subset of '
                'vCPUs in the flavor. See "hw:cpu_dedicated_mask"')
        raise exception.InvalidMixedInstanceDedicatedMask(msg)

    return pcpus


# NOTE(stephenfin): This must be public as it's used elsewhere
def get_realtime_cpu_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[ty.Set[int]]:
    """Validate and return the requested realtime CPU mask.

    :param flavor: ``nova.objects.Flavor`` instance
    :param image_meta: ``nova.objects.ImageMeta`` instance
    :returns: The realtime CPU set requested, else None.
    """
    if not is_realtime_enabled(flavor):
        return None

    flavor_mask, image_mask = _get_flavor_image_meta(
        'cpu_realtime_mask', flavor, image_meta)

    # Image masks are used ahead of flavor masks as they will have more
    # specific requirements
    mask = image_mask or flavor_mask

    vcpus_set = set(range(flavor.vcpus))
    if mask:
        if mask.strip().startswith('^'):
            vcpus_rt = parse_cpu_spec("0-%d,%s" % (flavor.vcpus - 1, mask))
        else:
            vcpus_rt = parse_cpu_spec("%s" % (mask))
    else:
        vcpus_rt = set(range(flavor.vcpus))

    if not vcpus_rt:
        raise exception.RealtimeMaskNotFoundOrInvalid()

    # TODO(stephenfin): Do this check in numa_get_constraints instead
    emu_policy = get_emulator_thread_policy_constraint(flavor)
    if vcpus_set == vcpus_rt and not emu_policy:
        raise exception.RealtimeMaskNotFoundOrInvalid()

    if not vcpus_rt.issubset(vcpus_set):
        msg = _("Realtime policy vCPU(s) mask is configured with RT vCPUs "
                "that are not a subset of the vCPUs in the flavor. See "
                "hw:cpu_realtime_mask or hw_cpu_realtime_mask")
        raise exception.RealtimeMaskNotFoundOrInvalid(msg)

    return vcpus_rt


# NOTE(stephenfin): This must be public as it's used elsewhere
def get_emulator_thread_policy_constraint(
    flavor: 'objects.Flavor',
) -> ty.Optional[str]:
    """Validate and return the requested emulator threads policy.

    :param flavor: ``nova.objects.Flavor`` instance
    :raises: exception.InvalidEmulatorThreadsPolicy if mask was not found or
        is invalid.
    :returns: The emulator thread policy requested, else None.
    """
    emu_threads_policy = flavor.get('extra_specs', {}).get(
        'hw:emulator_threads_policy')

    if not emu_threads_policy:
        return None

    if emu_threads_policy not in fields.CPUEmulatorThreadsPolicy.ALL:
        raise exception.InvalidEmulatorThreadsPolicy(
            requested=emu_threads_policy,
            available=str(fields.CPUEmulatorThreadsPolicy.ALL))

    return emu_threads_policy


def get_pci_numa_policy_constraint(flavor, image_meta):
    """Return pci numa affinity policy or None.

    :param flavor: a flavor object to read extra specs from
    :param image_meta: nova.objects.ImageMeta object instance
    :raises: nova.exception.ImagePCINUMAPolicyForbidden
    :raises: nova.exception.InvalidPCINUMAAffinity
    """
    flavor_policy, image_policy = _get_flavor_image_meta(
        'pci_numa_affinity_policy', flavor, image_meta)

    if flavor_policy and image_policy and flavor_policy != image_policy:
        raise exception.ImagePCINUMAPolicyForbidden()

    policy = flavor_policy or image_policy

    if policy and policy not in fields.PCINUMAAffinityPolicy.ALL:
        raise exception.InvalidPCINUMAAffinity(policy=policy)

    return policy


def get_vtpm_constraint(
    flavor: 'objects.Flavor',
    image_meta: 'objects.ImageMeta',
) -> ty.Optional[VTPMConfig]:
    """Validate and return the requested vTPM configuration.

    :param flavor: ``nova.objects.Flavor`` instance
    :param image_meta: ``nova.objects.ImageMeta`` instance
    :raises: nova.exception.FlavorImageConflict if a value is specified in both
        the flavor and the image, but the values do not match
    :raises: nova.exception.Invalid if a value or combination of values is
        invalid
    :returns: A named tuple containing the vTPM version and model, else None.
    """
    version = _get_unique_flavor_image_meta('tpm_version', flavor, image_meta)
    if version is None:
        return None

    if version not in fields.TPMVersion.ALL:
        raise exception.Invalid(
            "Invalid TPM version %(version)r. Allowed values: %(valid)s." %
            {'version': version, 'valid': ', '.join(fields.TPMVersion.ALL)}
        )

    model = _get_unique_flavor_image_meta('tpm_model', flavor, image_meta)
    if model is None:
        # model defaults to TIS
        model = fields.TPMModel.TIS
    elif model not in fields.TPMModel.ALL:
        raise exception.Invalid(
            "Invalid TPM model %(model)r. Allowed values: %(valid)s." %
            {'model': model, 'valid': ', '.join(fields.TPMModel.ALL)}
        )
    elif model == fields.TPMModel.CRB and version != fields.TPMVersion.v2_0:
        raise exception.Invalid(
            "TPM model CRB is only valid with TPM version 2.0."
        )

    return VTPMConfig(version, model)


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
    :raises: exception.BadRequirementEmulatorThreadsPolicy if CPU emulator
             threads policy conflicts with CPU allocation policy
    :raises: exception.InvalidCPUAllocationPolicy if policy is defined with
             invalid value in image or flavor.
    :raises: exception.InvalidCPUThreadAllocationPolicy if policy is defined
             with invalid value in image or flavor.
    :raises: exception.InvalidRequest if there is a conflict between explicitly
             and implicitly requested resources of hyperthreading traits
    :raises: exception.RequiredMixedInstancePolicy if dedicated CPU mask is
             provided in flavor while CPU policy is not 'mixed'.
    :raises: exception.RequiredMixedOrRealtimeCPUMask the mixed policy instance
             dedicated CPU mask can only be specified through either
             'hw:cpu_realtime_mask' or 'hw:cpu_dedicated_mask', not both.
    :raises: exception.InvalidMixedInstanceDedicatedMask if specify an invalid
             CPU mask for 'hw:cpu_dedicated_mask'.
    :returns: objects.InstanceNUMATopology, or None
    """

    cpu_policy = get_cpu_policy_constraint(flavor, image_meta)
    cpu_thread_policy = get_cpu_thread_policy_constraint(flavor, image_meta)
    realtime_cpus = get_realtime_cpu_constraint(flavor, image_meta)
    dedicated_cpus = get_dedicated_cpu_constraint(flavor)
    emu_threads_policy = get_emulator_thread_policy_constraint(flavor)

    # handle explicit VCPU/PCPU resource requests and the HW_CPU_HYPERTHREADING
    # trait

    requested_vcpus, requested_pcpus = _get_vcpu_pcpu_resources(flavor)

    if cpu_policy and (requested_vcpus or requested_pcpus):
        raise exception.InvalidRequest(
            "It is not possible to use the 'resources:VCPU' or "
            "'resources:PCPU' extra specs in combination with the "
            "'hw:cpu_policy' extra spec or 'hw_cpu_policy' image metadata "
            "property; use one or the other")

    if requested_vcpus and requested_pcpus:
        raise exception.InvalidRequest(
            "It is not possible to specify both 'resources:VCPU' and "
            "'resources:PCPU' extra specs; use one or the other")

    if requested_pcpus:
        if (emu_threads_policy == fields.CPUEmulatorThreadsPolicy.ISOLATE and
                flavor.vcpus + 1 != requested_pcpus):
            raise exception.InvalidRequest(
                "You have requested 'hw:emulator_threads_policy=isolate' but "
                "have not requested sufficient PCPUs to handle this policy; "
                "you must allocate exactly flavor.vcpus + 1 PCPUs.")

        if (emu_threads_policy != fields.CPUEmulatorThreadsPolicy.ISOLATE and
                flavor.vcpus != requested_pcpus):
            raise exception.InvalidRequest(
                "There is a mismatch between the number of PCPUs requested "
                "via 'resourcesNN:PCPU' and the flavor); you must allocate "
                "exactly flavor.vcpus PCPUs")

        cpu_policy = fields.CPUAllocationPolicy.DEDICATED

    if requested_vcpus:
        # NOTE(stephenfin): It would be nice if we could error out if
        # flavor.vcpus != resources:PCPU, but that would be a breaking change.
        # Better to wait until we remove flavor.vcpus or something
        cpu_policy = fields.CPUAllocationPolicy.SHARED

    hyperthreading_trait = _get_hyperthreading_trait(flavor, image_meta)

    if cpu_thread_policy and hyperthreading_trait:
        raise exception.InvalidRequest(
            "It is not possible to use the 'trait:HW_CPU_HYPERTHREADING' "
            "extra spec in combination with the 'hw:cpu_thread_policy' "
            "extra spec or 'hw_cpu_thread_policy' image metadata property; "
            "use one or the other")

    if hyperthreading_trait == 'forbidden':
        cpu_thread_policy = fields.CPUThreadAllocationPolicy.ISOLATE
    elif hyperthreading_trait == 'required':
        cpu_thread_policy = fields.CPUThreadAllocationPolicy.REQUIRE

    # sanity checks

    if cpu_policy in (fields.CPUAllocationPolicy.SHARED, None):
        if cpu_thread_policy:
            raise exception.CPUThreadPolicyConfigurationInvalid()

        if emu_threads_policy == fields.CPUEmulatorThreadsPolicy.ISOLATE:
            raise exception.BadRequirementEmulatorThreadsPolicy()

        # 'hw:cpu_dedicated_mask' should not be defined in a flavor with
        # 'shared' policy.
        if dedicated_cpus:
            raise exception.RequiredMixedInstancePolicy()

        if realtime_cpus:
            raise exception.RealtimeConfigurationInvalid()
    elif cpu_policy == fields.CPUAllocationPolicy.DEDICATED:
        # 'hw:cpu_dedicated_mask' should not be defined in a flavor with
        # 'dedicated' policy.
        if dedicated_cpus:
            raise exception.RequiredMixedInstancePolicy()
    else:  # MIXED
        if realtime_cpus and dedicated_cpus:
            raise exception.RequiredMixedOrRealtimeCPUMask()

        if not (realtime_cpus or dedicated_cpus):
            raise exception.RequiredMixedOrRealtimeCPUMask()

        # NOTE(huaquiang): If using mixed with realtime, then cores listed in
        # the realtime mask are dedicated and everything else is shared.
        dedicated_cpus = dedicated_cpus or realtime_cpus

    nodes = _get_numa_node_count_constraint(flavor, image_meta)
    pagesize = _get_numa_pagesize_constraint(flavor, image_meta)
    vpmems = get_vpmems(flavor)

    # If 'hw:cpu_dedicated_mask' is not found in flavor extra specs, the
    # 'dedicated_cpus' variable is None, while we hope it being an empty set.
    dedicated_cpus = dedicated_cpus or set()
    if cpu_policy == fields.CPUAllocationPolicy.DEDICATED:
        # But for an instance with 'dedicated' CPU allocation policy, all
        # CPUs are 'dedicated' CPUs, which is 1:1 pinned to a host CPU.
        dedicated_cpus = set(range(flavor.vcpus))

    # NOTE(stephenfin): There are currently four things that will configure a
    # NUMA topology for an instance:
    #
    # - The user explicitly requesting one
    # - The use of CPU pinning
    # - The use of hugepages
    # - The use of vPMEM
    if nodes or pagesize or vpmems or cpu_policy in (
        fields.CPUAllocationPolicy.DEDICATED,
        fields.CPUAllocationPolicy.MIXED,
    ):
        # NOTE(huaqiang): Here we build the instance dedicated CPU set and the
        # shared CPU set, through 'pcpus' and 'vcpus' respectively,
        # which will be used later to calculate the per-NUMA-cell CPU set.
        cpus = set(range(flavor.vcpus))
        pcpus = dedicated_cpus
        vcpus = cpus - pcpus

        nodes = nodes or 1
        cpu_list = _get_numa_cpu_constraint(flavor, image_meta)
        mem_list = _get_numa_mem_constraint(flavor, image_meta)

        if cpu_list is None and mem_list is None:
            numa_topology = _get_numa_topology_auto(
                nodes, flavor, vcpus, pcpus,
            )
        elif cpu_list is not None and mem_list is not None:
            # If any node has data set, all nodes must have data set
            if len(cpu_list) != nodes or len(mem_list) != nodes:
                raise exception.ImageNUMATopologyIncomplete()

            numa_topology = _get_numa_topology_manual(
                nodes, flavor, vcpus, pcpus, cpu_list, mem_list
            )
        else:
            # If one property list is specified both must be
            raise exception.ImageNUMATopologyIncomplete()

        # We currently support the same pagesize, CPU policy and CPU thread
        # policy for all cells, but these are still stored on a per-cell
        # basis :(
        for c in numa_topology.cells:
            setattr(c, 'pagesize', pagesize)
            setattr(c, 'cpu_policy', cpu_policy)
            setattr(c, 'cpu_thread_policy', cpu_thread_policy)

        # ...but emulator threads policy is not \o/
        numa_topology.emulator_threads_policy = emu_threads_policy
    else:
        numa_topology = None

    return numa_topology


def _numa_cells_support_network_metadata(
    host_topology: 'objects.NUMATopology',
    chosen_host_cells: ty.List['objects.NUMACell'],
    network_metadata: 'objects.NetworkMetadata',
) -> bool:
    """Determine whether the cells can accept the network requests.

    :param host_topology: The entire host topology, used to find non-chosen
        host cells.
    :param chosen_host_cells: List of NUMACells to extract possible network
        NUMA affinity from.
    :param network_metadata: The combined summary of physnets and tunneled
        networks required by this topology or None.

    :return: True if any NUMA affinity constraints for requested networks can
        be satisfied, else False
    """
    if not network_metadata:
        return True

    required_physnets: ty.Set[str] = set()
    if 'physnets' in network_metadata:
        # use set() to avoid modifying the original data structure
        required_physnets = set(network_metadata.physnets)

    required_tunnel: bool = False
    if 'tunneled' in network_metadata:
        required_tunnel = network_metadata.tunneled

    if required_physnets:
        # identify requested physnets that have an affinity to any of our
        # chosen host NUMA cells
        for host_cell in chosen_host_cells:
            if 'network_metadata' not in host_cell:
                continue

            # if one of these cells provides affinity for one or more physnets,
            # drop said physnet(s) from the list we're searching for
            required_physnets -= required_physnets.intersection(
                host_cell.network_metadata.physnets)

        # however, if we still require some level of NUMA affinity, we need
        # to make sure one of the other NUMA cells isn't providing that; note
        # that NUMA affinity might not be provided for all physnets so we are
        # in effect skipping these
        for host_cell in host_topology.cells:
            if 'network_metadata' not in host_cell:
                continue

            # if one of these cells provides affinity for one or more physnets,
            # we need to fail because we should be using that node and are not
            if required_physnets.intersection(
                    host_cell.network_metadata.physnets):
                return False

    if required_tunnel:
        # identify if tunneled networks have an affinity to any of our chosen
        # host NUMA cells
        for host_cell in chosen_host_cells:
            if 'network_metadata' not in host_cell:
                continue

            if host_cell.network_metadata.tunneled:
                return True

        # however, if we still require some level of NUMA affinity, we need to
        # make sure one of the other NUMA cells isn't providing that; note
        # that, as with physnets, NUMA affinity might not be defined for
        # tunneled networks and we'll simply continue if this is the case
        for host_cell in host_topology.cells:
            if 'network_metadata' not in host_cell:
                continue

            if host_cell.network_metadata.tunneled:
                return False

    return True


def numa_fit_instance_to_host(
    host_topology: 'objects.NUMATopology',
    instance_topology: 'objects.InstanceNUMATopology',
    limits: ty.Optional['objects.NUMATopologyLimit'] = None,
    pci_requests: ty.Optional['objects.InstancePCIRequests'] = None,
    pci_stats: ty.Optional[stats.PciDeviceStats] = None,
):
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

    network_metadata = None
    if limits and 'network_metadata' in limits:
        network_metadata = limits.network_metadata

    host_cells = host_topology.cells

    # If PCI device(s) are not required, prefer host cells that don't have
    # devices attached. Presence of a given numa_node in a PCI pool is
    # indicative of a PCI device being associated with that node
    if not pci_requests and pci_stats:
        # TODO(stephenfin): pci_stats can't be None here but mypy can't figure
        # that out for some reason
        host_cells = sorted(host_cells, key=lambda cell: cell.id in [
            pool['numa_node'] for pool in pci_stats.pools])  # type: ignore

    for host_cell_perm in itertools.permutations(
            host_cells, len(instance_topology)):
        chosen_instance_cells: ty.List['objects.InstanceNUMACell'] = []
        chosen_host_cells: ty.List['objects.NUMACell'] = []
        for host_cell, instance_cell in zip(
                host_cell_perm, instance_topology.cells):
            try:
                cpuset_reserved = 0
                if (instance_topology.emulator_threads_isolated and
                    len(chosen_instance_cells) == 0):
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
            chosen_host_cells.append(host_cell)
            chosen_instance_cells.append(got_cell)

        if len(chosen_instance_cells) != len(host_cell_perm):
            continue

        if pci_requests and pci_stats and not pci_stats.support_requests(
                pci_requests, chosen_instance_cells):
            continue

        if network_metadata and not _numa_cells_support_network_metadata(
                host_topology, chosen_host_cells, network_metadata):
            continue

        return objects.InstanceNUMATopology(
            cells=chosen_instance_cells,
            emulator_threads_policy=emulator_threads_policy)


def numa_get_reserved_huge_pages():
    """Returns reserved memory pages from host option.

    Based from the compute node option reserved_huge_pages, generate
    a well formatted list of dict which can be used to build a valid
    NUMATopology.

    :raises: exception.InvalidReservedMemoryPagesOption when
             reserved_huge_pages option is not correctly set.
    :returns: A dict of dicts keyed by NUMA node IDs; keys of child dict
              are pages size and values of the number reserved.
    """
    if not CONF.reserved_huge_pages:
        return {}

    try:
        bucket: ty.Dict[int, ty.Dict[int, int]] = collections.defaultdict(dict)
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


def _get_smallest_pagesize(host_cell):
    """Returns the smallest available page size based on hostcell"""
    avail_pagesize = [page.size_kb for page in host_cell.mempages]
    avail_pagesize.sort()
    return avail_pagesize[0]


def _numa_pagesize_usage_from_cell(host_cell, instance_cell, sign):
    if 'pagesize' in instance_cell and instance_cell.pagesize:
        pagesize = instance_cell.pagesize
    else:
        pagesize = _get_smallest_pagesize(host_cell)

    topo = []
    for pages in host_cell.mempages:
        if pages.size_kb == pagesize:
            topo.append(objects.NUMAPagesTopology(
                size_kb=pages.size_kb,
                total=pages.total,
                used=max(0, pages.used +
                         instance_cell.memory * units.Ki /
                         pages.size_kb * sign),
                reserved=pages.reserved if 'reserved' in pages else 0))
        else:
            topo.append(pages)
    return topo


def numa_usage_from_instance_numa(host_topology, instance_topology,
                                  free=False):
    """Update the host topology usage.

    Update the host NUMA topology based on usage by the provided instance NUMA
    topology.

    :param host_topology: objects.NUMATopology to update usage information
    :param instance_topology: objects.InstanceNUMATopology from which to
        retrieve usage information.
    :param free: If true, decrease, rather than increase, host usage based on
        instance usage.

    :returns: Updated objects.NUMATopology for host
    """
    if not host_topology or not instance_topology:
        return host_topology

    cells = []
    sign = -1 if free else 1

    for host_cell in host_topology.cells:
        memory_usage = host_cell.memory_usage
        shared_cpus_usage = host_cell.cpu_usage

        new_cell = objects.NUMACell(
            id=host_cell.id,
            cpuset=host_cell.cpuset,
            pcpuset=host_cell.pcpuset,
            memory=host_cell.memory,
            cpu_usage=0,
            memory_usage=0,
            mempages=host_cell.mempages,
            pinned_cpus=host_cell.pinned_cpus,
            siblings=host_cell.siblings)

        if 'network_metadata' in host_cell:
            new_cell.network_metadata = host_cell.network_metadata

        for cellid, instance_cell in enumerate(instance_topology.cells):
            if instance_cell.id != host_cell.id:
                continue

            new_cell.mempages = _numa_pagesize_usage_from_cell(
                new_cell, instance_cell, sign)

            memory_usage = memory_usage + sign * instance_cell.memory

            shared_cpus_usage += sign * len(instance_cell.cpuset)

            if instance_cell.cpu_policy in (
                None, fields.CPUAllocationPolicy.SHARED,
            ):
                continue

            pinned_cpus = set(instance_cell.cpu_pinning.values())
            if instance_cell.cpuset_reserved:
                pinned_cpus |= instance_cell.cpuset_reserved

            if free:
                if (instance_cell.cpu_thread_policy ==
                        fields.CPUThreadAllocationPolicy.ISOLATE):
                    new_cell.unpin_cpus_with_siblings(pinned_cpus)
                else:
                    new_cell.unpin_cpus(pinned_cpus)
            else:
                if (instance_cell.cpu_thread_policy ==
                        fields.CPUThreadAllocationPolicy.ISOLATE):
                    new_cell.pin_cpus_with_siblings(pinned_cpus)
                else:
                    new_cell.pin_cpus(pinned_cpus)

        # NOTE(stephenfin): We don't need to set 'pinned_cpus' here since that
        # was done in the above '(un)pin_cpus(_with_siblings)' functions
        new_cell.memory_usage = max(0, memory_usage)
        new_cell.cpu_usage = max(0, shared_cpus_usage)
        cells.append(new_cell)

    return objects.NUMATopology(cells=cells)


def get_vpmems(flavor):
    """Return vpmems related to input request.

    :param flavor: a flavor object to read extra specs from
    :returns: a vpmem label list
    """
    vpmems_info = flavor.get('extra_specs', {}).get('hw:pmem')
    if not vpmems_info:
        return []
    vpmem_labels = vpmems_info.split(',')
    formed_labels = []
    for label in vpmem_labels:
        formed_label = label.strip()
        if formed_label:
            formed_labels.append(formed_label)
    return formed_labels


def check_hw_rescue_props(image_meta):
    """Confirm that hw_rescue_* image properties are present.
    """
    hw_rescue_props = ['hw_rescue_device', 'hw_rescue_bus']
    return any(key in image_meta.properties for key in hw_rescue_props)
