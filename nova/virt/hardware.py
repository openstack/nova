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

from nova import exception
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class VirtCPUTopology(object):

    def __init__(self, sockets, cores, threads):
        """Create a new CPU topology object

        :param sockets: number of sockets, at least 1
        :param cores: number of cores, at least 1
        :param threads: number of threads, at least 1

        Create a new CPU topology object representing the
        number of sockets, cores and threads to use for
        the virtual instance.
        """

        self.sockets = sockets
        self.cores = cores
        self.threads = threads

    def score(self, wanttopology):
        """Calculate score for the topology against a desired configuration

        :param wanttopology: VirtCPUTopology instance for preferred topology

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
            self.sockets == wanttopology.sockets):
            score = score + 1
        if (wanttopology.cores != -1 and
            self.cores == wanttopology.cores):
            score = score + 1
        if (wanttopology.threads != -1 and
            self.threads == wanttopology.threads):
            score = score + 1
        return score

    @staticmethod
    def get_topology_constraints(flavor, image_meta):
        """Get the topology constraints declared in flavour or image

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

        This will return a pair of VirtCPUTopology instances,
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

        return (VirtCPUTopology(sockets, cores, threads),
                VirtCPUTopology(maxsockets, maxcores, maxthreads))

    @staticmethod
    def get_possible_topologies(vcpus, maxtopology, allow_threads):
        """Get a list of possible topologies for a vCPU count
        :param vcpus: total number of CPUs for guest instance
        :param maxtopology: VirtCPUTopology for upper limits
        :param allow_threads: if the hypervisor supports CPU threads

        Given a total desired vCPU count and constraints on the
        maximum number of sockets, cores and threads, return a
        list of VirtCPUTopology instances that represent every
        possible topology that satisfies the constraints.

        exception.ImageVCPULimitsRangeImpossible is raised if
        it is impossible to achieve the total vcpu count given
        the maximum limits on sockets, cores & threads.

        :returns: list of VirtCPUTopology instances
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
                        possible.append(VirtCPUTopology(s, c, t))

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

    @staticmethod
    def sort_possible_topologies(possible, wanttopology):
        """Sort the topologies in order of preference
        :param possible: list of VirtCPUTopology instances
        :param wanttopology: VirtCPUTopology for preferred topology

        This takes the list of possible topologies and resorts
        it such that those configurations which most closely
        match the preferred topology are first.

        :returns: sorted list of VirtCPUTopology instances
        """

        # Look at possible topologies and score them according
        # to how well they match the preferred topologies
        # We don't use python's sort(), since we want to
        # preserve the sorting done when populating the
        # 'possible' list originally
        scores = collections.defaultdict(list)
        for topology in possible:
            score = topology.score(wanttopology)
            scores[score].append(topology)

        # Build list of all possible topologies sorted
        # by the match score, best match first
        desired = []
        desired.extend(scores[3])
        desired.extend(scores[2])
        desired.extend(scores[1])
        desired.extend(scores[0])

        return desired

    @staticmethod
    def get_desirable_configs(flavor, image_meta, allow_threads=True):
        """Get desired CPU topologies according to settings

        :param flavor: Flavor object to query extra specs from
        :param image_meta: ImageMeta object to query properties from
        :param allow_threads: if the hypervisor supports CPU threads

        Look at the properties set in the flavor extra specs and
        the image metadata and build up a list of all possible
        valid CPU topologies that can be used in the guest. Then
        return this list sorted in order of preference.

        :returns: sorted list of VirtCPUTopology instances
        """

        LOG.debug("Getting desirable topologies for flavor %(flavor)s "
                  "and image_meta %(image_meta)s",
                  {"flavor": flavor, "image_meta": image_meta})

        preferred, maximum = (
            VirtCPUTopology.get_topology_constraints(flavor,
                                                     image_meta))

        possible = VirtCPUTopology.get_possible_topologies(
            flavor.vcpus, maximum, allow_threads)
        desired = VirtCPUTopology.sort_possible_topologies(
            possible, preferred)

        return desired

    @staticmethod
    def get_best_config(flavor, image_meta, allow_threads=True):
        """Get bst CPU topology according to settings

        :param flavor: Flavor object to query extra specs from
        :param image_meta: ImageMeta object to query properties from
        :param allow_threads: if the hypervisor supports CPU threads

        Look at the properties set in the flavor extra specs and
        the image metadata and build up a list of all possible
        valid CPU topologies that can be used in the guest. Then
        return the best topology to use

        :returns: a VirtCPUTopology instance for best topology
        """

        return VirtCPUTopology.get_desirable_configs(flavor,
                                                     image_meta,
                                                     allow_threads)[0]
