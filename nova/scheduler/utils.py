# All Rights Reserved.
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

"""Utility methods for scheduling."""

import collections
import re
import sys
import traceback

import os_resource_classes as orc
import os_traits
from oslo_log import log as logging
from oslo_serialization import jsonutils
from six.moves.urllib import parse

from nova.compute import flavors
from nova.compute import utils as compute_utils
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields as obj_fields
from nova.objects import instance as obj_instance
from nova import rpc
from nova.scheduler.filters import utils as filters_utils
from nova.virt import hardware


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

GroupDetails = collections.namedtuple('GroupDetails', ['hosts', 'policy',
                                                       'members'])


class ResourceRequest(object):
    """Presents a granular resource request via RequestGroup instances."""
    # extra_specs-specific consts
    XS_RES_PREFIX = 'resources'
    XS_TRAIT_PREFIX = 'trait'
    # Regex patterns for numbered or un-numbered resources/trait keys
    XS_KEYPAT = re.compile(r"^(%s)([1-9][0-9]*)?:(.*)$" %
                           '|'.join((XS_RES_PREFIX, XS_TRAIT_PREFIX)))

    def __init__(self, request_spec, enable_pinning_translate=True):
        """Create a new instance of ResourceRequest from a RequestSpec.

        Examines the flavor, flavor extra specs, and (optional) image metadata
        of the provided ``request_spec``.

        For extra specs, items of the following form are examined:

        - ``resources:$RESOURCE_CLASS``: $AMOUNT
        - ``resources$N:$RESOURCE_CLASS``: $AMOUNT
        - ``trait:$TRAIT_NAME``: "required"
        - ``trait$N:$TRAIT_NAME``: "required"

        .. note::

            This does *not* yet handle ``member_of[$N]``.

        For image metadata, traits are extracted from the ``traits_required``
        property, if present.

        For the flavor, ``VCPU``, ``MEMORY_MB`` and ``DISK_GB`` are calculated
        from Flavor properties, though these are only used if they aren't
        overridden by flavor extra specs.

        :param request_spec: An instance of ``objects.RequestSpec``.
        :param enable_pinning_translate: True if the CPU policy extra specs
            should be translated to placement resources and traits.
        """
        # { ident: RequestGroup }
        self._rg_by_id = {}
        self._group_policy = None
        # Default to the configured limit but _limit can be
        # set to None to indicate "no limit".
        self._limit = CONF.scheduler.max_placement_results

        # TODO(efried): Handle member_of[$N], which will need to be reconciled
        # with destination.aggregates handling in resources_from_request_spec

        # request_spec.image is nullable
        if 'image' in request_spec and request_spec.image:
            image = request_spec.image
        else:
            image = objects.ImageMeta(properties=objects.ImageMetaProps())

        # Parse the flavor extra specs
        self._process_extra_specs(request_spec.flavor)

        self.numbered_groups_from_flavor = self.get_num_of_numbered_groups()

        # Now parse the (optional) image metadata
        self._process_image_meta(image)

        # TODO(stephenfin): Remove this parameter once we drop support for
        # 'vcpu_pin_set'
        self.cpu_pinning_requested = False

        if enable_pinning_translate:
            # Next up, let's handle those pesky CPU pinning policies
            self._translate_pinning_policies(request_spec.flavor, image)

        # Finally, parse the flavor itself, though we'll only use these fields
        # if they don't conflict with something already provided by the flavor
        # extra specs. These are all added to the unnumbered request group.
        merged_resources = self.merged_resources()

        if (orc.VCPU not in merged_resources and
                orc.PCPU not in merged_resources):
            self._add_resource(None, orc.VCPU, request_spec.vcpus)

        if orc.MEMORY_MB not in merged_resources:
            self._add_resource(None, orc.MEMORY_MB, request_spec.memory_mb)

        if orc.DISK_GB not in merged_resources:
            disk = request_spec.ephemeral_gb
            disk += compute_utils.convert_mb_to_ceil_gb(request_spec.swap)
            if 'is_bfv' not in request_spec or not request_spec.is_bfv:
                disk += request_spec.root_gb

            if disk:
                self._add_resource(None, orc.DISK_GB, disk)

        self._translate_memory_encryption(request_spec.flavor, image)

        self._translate_vpmems_request(request_spec.flavor)

        self.strip_zeros()

    def _process_extra_specs(self, flavor):
        if 'extra_specs' not in flavor:
            return

        for key, val in flavor.extra_specs.items():
            if key == 'group_policy':
                self._add_group_policy(val)
                continue

            match = self.XS_KEYPAT.match(key)
            if not match:
                continue

            # 'prefix' is 'resources' or 'trait'
            # 'suffix' is $N or None
            # 'name' is either the resource class name or the trait name.
            prefix, suffix, name = match.groups()

            # Process "resources[$N]"
            if prefix == self.XS_RES_PREFIX:
                self._add_resource(suffix, name, val)

            # Process "trait[$N]"
            elif prefix == self.XS_TRAIT_PREFIX:
                self._add_trait(suffix, name, val)

    def _process_image_meta(self, image):
        if not image or 'properties' not in image:
            return

        for trait in image.properties.get('traits_required', []):
            # required traits from the image are always added to the
            # unnumbered request group, granular request groups are not
            # supported in image traits
            self._add_trait(None, trait, "required")

    def _translate_memory_encryption(self, flavor, image):
        """When the hw:mem_encryption extra spec or the hw_mem_encryption
        image property are requested, translate into a request for
        resources:MEM_ENCRYPTION_CONTEXT=1 which requires a slot on a
        host which can support encryption of the guest memory.
        """
        # NOTE(aspiers): In theory this could raise FlavorImageConflict,
        # but we already check it in the API layer, so that should never
        # happen.
        if not hardware.get_mem_encryption_constraint(flavor, image):
            # No memory encryption required, so no further action required.
            return

        self._add_resource(None, orc.MEM_ENCRYPTION_CONTEXT, 1)
        LOG.debug("Added %s=1 to requested resources",
                  orc.MEM_ENCRYPTION_CONTEXT)

    def _translate_vpmems_request(self, flavor):
        """When the hw:pmem extra spec is present, require hosts which can
        provide enough vpmem resources.
        """
        vpmem_labels = hardware.get_vpmems(flavor)
        if not vpmem_labels:
            # No vpmems required
            return
        amount_by_rc = collections.defaultdict(int)
        for vpmem_label in vpmem_labels:
            resource_class = orc.normalize_name(
                "PMEM_NAMESPACE_" + vpmem_label)
            amount_by_rc[resource_class] += 1
        for resource_class, amount in amount_by_rc.items():
            self._add_resource(None, resource_class, amount)
            LOG.debug("Added resource %s=%d to requested resources",
                      resource_class, amount)

    def _translate_pinning_policies(self, flavor, image):
        """Translate the legacy pinning policies to resource requests."""
        # NOTE(stephenfin): These can raise exceptions but these have already
        # been validated by 'nova.virt.hardware.numa_get_constraints' in the
        # API layer (see change I06fad233006c7bab14749a51ffa226c3801f951b).
        # This call also handles conflicts between explicit VCPU/PCPU
        # requests and implicit 'hw:cpu_policy'-based requests, mismatches
        # between the number of CPUs in the flavor and explicit VCPU/PCPU
        # requests, etc.
        cpu_policy = hardware.get_cpu_policy_constraint(
            flavor, image)
        cpu_thread_policy = hardware.get_cpu_thread_policy_constraint(
            flavor, image)
        emul_thread_policy = hardware.get_emulator_thread_policy_constraint(
            flavor)

        # We don't need to worry about handling 'SHARED' - that will result in
        # VCPUs which we include by default
        if cpu_policy == obj_fields.CPUAllocationPolicy.DEDICATED:
            # TODO(stephenfin): Remove when we drop support for 'vcpu_pin_set'
            self.cpu_pinning_requested = True

            # Switch VCPU -> PCPU
            cpus = flavor.vcpus

            LOG.debug('Translating request for %(vcpu_rc)s=%(cpus)d to '
                      '%(vcpu_rc)s=0,%(pcpu_rc)s=%(cpus)d',
                      {'vcpu_rc': orc.VCPU, 'pcpu_rc': orc.PCPU,
                       'cpus': cpus})

            if emul_thread_policy == 'isolate':
                cpus += 1

                LOG.debug('Adding additional %(pcpu_rc)s to account for '
                          'emulator threads', {'pcpu_rc': orc.PCPU})

            self._add_resource(None, orc.PCPU, cpus)

        trait = {
            obj_fields.CPUThreadAllocationPolicy.ISOLATE: 'forbidden',
            obj_fields.CPUThreadAllocationPolicy.REQUIRE: 'required',
        }.get(cpu_thread_policy)
        if trait:
            LOG.debug('Adding %(trait)s=%(value)s trait',
                      {'trait': os_traits.HW_CPU_HYPERTHREADING,
                       'value': trait})
            self._add_trait(None, os_traits.HW_CPU_HYPERTHREADING, trait)

    @property
    def group_policy(self):
        return self._group_policy

    @group_policy.setter
    def group_policy(self, value):
        self._group_policy = value

    def get_request_group(self, ident):
        if ident not in self._rg_by_id:
            rq_grp = objects.RequestGroup(use_same_provider=bool(ident))
            self._rg_by_id[ident] = rq_grp
        return self._rg_by_id[ident]

    def add_request_group(self, request_group):
        """Inserts the existing group with a unique integer id

        The groups coming from the flavor can have arbitrary ids but every id
        is an integer. So this function can ensure unique ids by using bigger
        ids than the maximum of existing ids.

        :param request_group: the RequestGroup to be added
        """
        # NOTE(gibi) [0] just here to always have a defined maximum
        group_idents = [0] + [int(ident) for ident in self._rg_by_id if ident]
        ident = max(group_idents) + 1
        self._rg_by_id[ident] = request_group

    def _add_resource(self, groupid, rclass, amount):
        # Validate the class.
        if not (rclass.startswith(orc.CUSTOM_NAMESPACE) or
                        rclass in orc.STANDARDS):
            LOG.warning(
                "Received an invalid ResourceClass '%(key)s' in extra_specs.",
                {"key": rclass})
            return
        # val represents the amount.  Convert to int, or warn and skip.
        try:
            amount = int(amount)
            if amount < 0:
                raise ValueError()
        except ValueError:
            LOG.warning(
                "Resource amounts must be nonnegative integers. Received "
                "'%(val)s' for key resources%(groupid)s.",
                {"groupid": groupid or '', "val": amount})
            return
        self.get_request_group(groupid).resources[rclass] = amount

    def _add_trait(self, groupid, trait_name, trait_type):
        # Currently the only valid values for a trait entry are 'required'
        # and 'forbidden'
        trait_vals = ('required', 'forbidden')
        if trait_type == 'required':
            self.get_request_group(groupid).required_traits.add(trait_name)
        elif trait_type == 'forbidden':
            self.get_request_group(groupid).forbidden_traits.add(trait_name)
        else:
            LOG.warning(
                "Only (%(tvals)s) traits are supported. Received '%(val)s' "
                "for key trait%(groupid)s.",
                {"tvals": ', '.join(trait_vals), "groupid": groupid or '',
                 "val": trait_type})
        return

    def _add_group_policy(self, policy):
        # The only valid values for group_policy are 'none' and 'isolate'.
        if policy not in ('none', 'isolate'):
            LOG.warning(
                "Invalid group_policy '%s'. Valid values are 'none' and "
                "'isolate'.", policy)
            return
        self._group_policy = policy

    def resource_groups(self):
        for rg in self._rg_by_id.values():
            yield rg.resources

    def get_num_of_numbered_groups(self):
        return len([ident for ident in self._rg_by_id.keys()
                    if ident is not None])

    def merged_resources(self):
        """Returns a merge of {resource_class: amount} for all resource groups.

        Amounts of the same resource class from different groups are added
        together.

        :return: A dict of the form {resource_class: amount}
        """
        ret = collections.defaultdict(lambda: 0)
        for resource_dict in self.resource_groups():
            for resource_class, amount in resource_dict.items():
                ret[resource_class] += amount
        return dict(ret)

    def _clean_empties(self):
        """Get rid of any empty ResourceGroup instances."""
        for ident, rg in list(self._rg_by_id.items()):
            if not any((rg.resources, rg.required_traits,
                        rg.forbidden_traits)):
                self._rg_by_id.pop(ident)

    def strip_zeros(self):
        """Remove any resources whose amounts are zero."""
        for resource_dict in self.resource_groups():
            for rclass in list(resource_dict):
                if resource_dict[rclass] == 0:
                    resource_dict.pop(rclass)
        self._clean_empties()

    def to_querystring(self):
        """Produce a querystring of the form expected by
        GET /allocation_candidates.
        """
        # TODO(gibi): We have a RequestGroup OVO so we can move this to that
        # class as a member function.
        # NOTE(efried): The sorting herein is not necessary for the API; it is
        # to make testing easier and logging/debugging predictable.
        def to_queryparams(request_group, suffix):
            res = request_group.resources
            required_traits = request_group.required_traits
            forbidden_traits = request_group.forbidden_traits
            aggregates = request_group.aggregates
            in_tree = request_group.in_tree
            forbidden_aggregates = request_group.forbidden_aggregates

            resource_query = ",".join(
                sorted("%s:%s" % (rc, amount)
                       for (rc, amount) in res.items()))
            qs_params = [('resources%s' % suffix, resource_query)]

            # Assemble required and forbidden traits, allowing for either/both
            # to be empty.
            required_val = ','.join(
                sorted(required_traits) +
                ['!%s' % ft for ft in sorted(forbidden_traits)])
            if required_val:
                qs_params.append(('required%s' % suffix, required_val))
            if aggregates:
                aggs = []
                # member_ofN is a list of lists.  We need a tuple of
                # ('member_ofN', 'in:uuid,uuid,...') for each inner list.
                for agglist in aggregates:
                    aggs.append(('member_of%s' % suffix,
                                 'in:' + ','.join(sorted(agglist))))
                qs_params.extend(sorted(aggs))
            if in_tree:
                qs_params.append(('in_tree%s' % suffix, in_tree))
            if forbidden_aggregates:
                # member_ofN is a list of aggregate uuids. We need a
                # tuple of ('member_ofN, '!in:uuid,uuid,...').
                forbidden_aggs = '!in:' + ','.join(
                    sorted(forbidden_aggregates))
                qs_params.append(('member_of%s' % suffix, forbidden_aggs))
            return qs_params

        if self._limit is not None:
            qparams = [('limit', self._limit)]
        else:
            qparams = []
        if self._group_policy is not None:
            qparams.append(('group_policy', self._group_policy))

        for ident, rg in self._rg_by_id.items():
            # [('resourcesN', 'rclass:amount,rclass:amount,...'),
            #  ('requiredN', 'trait_name,!trait_name,...'),
            #  ('member_ofN', 'in:uuid,uuid,...'),
            #  ('member_ofN', 'in:uuid,uuid,...')]
            qparams.extend(to_queryparams(rg, ident or ''))

        return parse.urlencode(sorted(qparams))

    @property
    def all_required_traits(self):
        traits = set()
        for rr in self._rg_by_id.values():
            traits = traits.union(rr.required_traits)
        return traits

    def __str__(self):
        return ', '.join(sorted(
            list(str(rg) for rg in list(self._rg_by_id.values()))))


def build_request_spec(image, instances, instance_type=None):
    """Build a request_spec for the scheduler.

    The request_spec assumes that all instances to be scheduled are the same
    type.

    :param image: optional primitive image meta dict
    :param instances: list of instances; objects will be converted to
        primitives
    :param instance_type: optional flavor; objects will be converted to
        primitives
    :return: dict with the following keys::

        'image': the image dict passed in or {}
        'instance_properties': primitive version of the first instance passed
        'instance_type': primitive version of the instance_type or None
        'num_instances': the number of instances passed in
    """
    instance = instances[0]
    if instance_type is None:
        if isinstance(instance, obj_instance.Instance):
            instance_type = instance.get_flavor()
        else:
            instance_type = flavors.extract_flavor(instance)

    if isinstance(instance, obj_instance.Instance):
        instance = obj_base.obj_to_primitive(instance)
        # obj_to_primitive doesn't copy this enough, so be sure
        # to detach our metadata blob because we modify it below.
        instance['system_metadata'] = dict(instance.get('system_metadata', {}))

    if isinstance(instance_type, objects.Flavor):
        instance_type = obj_base.obj_to_primitive(instance_type)
        # NOTE(danms): Replicate this old behavior because the
        # scheduler RPC interface technically expects it to be
        # there. Remove this when we bump the scheduler RPC API to
        # v5.0
        try:
            flavors.save_flavor_info(instance.get('system_metadata', {}),
                                     instance_type)
        except KeyError:
            # If the flavor isn't complete (which is legit with a
            # flavor object, just don't put it in the request spec
            pass

    request_spec = {
            'image': image or {},
            'instance_properties': instance,
            'instance_type': instance_type,
            'num_instances': len(instances)}
    # NOTE(mriedem): obj_to_primitive above does not serialize everything
    # in an object, like datetime fields, so we need to still call to_primitive
    # to recursively serialize the items in the request_spec dict.
    return jsonutils.to_primitive(request_spec)


def resources_from_flavor(instance, flavor):
    """Convert a flavor into a set of resources for placement, taking into
    account boot-from-volume instances.

    This takes an instance and a flavor and returns a dict of
    resource_class:amount based on the attributes of the flavor, accounting for
    any overrides that are made in extra_specs.
    """
    is_bfv = compute_utils.is_volume_backed_instance(instance._context,
                                                     instance)
    # create a fake RequestSpec as a wrapper to the caller
    req_spec = objects.RequestSpec(flavor=flavor, is_bfv=is_bfv)

    # TODO(efried): This method is currently only used from places that
    # assume the compute node is the only resource provider.  So for now, we
    # just merge together all the resources specified in the flavor and pass
    # them along.  This will need to be adjusted when nested and/or shared RPs
    # are in play.
    res_req = ResourceRequest(req_spec)

    return res_req.merged_resources()


def resources_from_request_spec(ctxt, spec_obj, host_manager,
        enable_pinning_translate=True):
    """Given a RequestSpec object, returns a ResourceRequest of the resources,
    traits, and aggregates it represents.

    :param context: The request context.
    :param spec_obj: A RequestSpec object.
    :param host_manager: A HostManager object.
    :param enable_pinning_translate: True if the CPU policy extra specs should
        be translated to placement resources and traits.

    :return: A ResourceRequest object.
    :raises NoValidHost: If the specified host/node is not found in the DB.
    """
    res_req = ResourceRequest(spec_obj, enable_pinning_translate)

    requested_resources = (spec_obj.requested_resources
                           if 'requested_resources' in spec_obj and
                              spec_obj.requested_resources
                           else [])
    for group in requested_resources:
        res_req.add_request_group(group)

    # values to get the destination target compute uuid
    target_host = None
    target_node = None
    target_cell = None

    if 'requested_destination' in spec_obj:
        destination = spec_obj.requested_destination
        if destination:
            if 'host' in destination:
                target_host = destination.host
            if 'node' in destination:
                target_node = destination.node
            if 'cell' in destination:
                target_cell = destination.cell
            if destination.aggregates:
                grp = res_req.get_request_group(None)
                # If the target must be either in aggA *or* in aggB and must
                # definitely be in aggC, the  destination.aggregates would be
                #     ['aggA,aggB', 'aggC']
                # Here we are converting it to
                #     [['aggA', 'aggB'], ['aggC']]
                grp.aggregates = [ored.split(',')
                                  for ored in destination.aggregates]
            if destination.forbidden_aggregates:
                grp = res_req.get_request_group(None)
                grp.forbidden_aggregates |= destination.forbidden_aggregates

    if 'force_hosts' in spec_obj and spec_obj.force_hosts:
        # Prioritize the value from requested_destination just in case
        # so that we don't inadvertently overwrite it to the old value
        # of force_hosts persisted in the DB
        target_host = target_host or spec_obj.force_hosts[0]

    if 'force_nodes' in spec_obj and spec_obj.force_nodes:
        # Prioritize the value from requested_destination just in case
        # so that we don't inadvertently overwrite it to the old value
        # of force_nodes persisted in the DB
        target_node = target_node or spec_obj.force_nodes[0]

    if target_host or target_node:
        nodes = host_manager.get_compute_nodes_by_host_or_node(
            ctxt, target_host, target_node, cell=target_cell)
        if not nodes:
            reason = (_('No such host - host: %(host)s node: %(node)s ') %
                      {'host': target_host, 'node': target_node})
            raise exception.NoValidHost(reason=reason)
        if len(nodes) == 1:
            if 'requested_destination' in spec_obj and destination:
                # When we only supply hypervisor_hostname in api to create a
                # server, the destination object will only include the node.
                # Here when we get one node, we set both host and node to
                # destination object. So we can reduce the number of HostState
                # objects to run through the filters.
                destination.host = nodes[0].host
                destination.node = nodes[0].hypervisor_hostname
            grp = res_req.get_request_group(None)
            grp.in_tree = nodes[0].uuid
        else:
            # Multiple nodes are found when a target host is specified
            # without a specific node. Since placement doesn't support
            # multiple uuids in the `in_tree` queryparam, what we can do here
            # is to remove the limit from the `GET /a_c` query to prevent
            # the found nodes from being filtered out in placement.
            res_req._limit = None

    # Don't limit allocation candidates when using affinity/anti-affinity.
    if ('scheduler_hints' in spec_obj and any(
        key in ['group', 'same_host', 'different_host']
        for key in spec_obj.scheduler_hints)):
        res_req._limit = None

    if res_req.get_num_of_numbered_groups() >= 2 and not res_req.group_policy:
        LOG.warning(
            "There is more than one numbered request group in the "
            "allocation candidate query but the flavor did not specify "
            "any group policy. This query would fail in placement due to "
            "the missing group policy. If you specified more than one "
            "numbered request group in the flavor extra_spec then you need to "
            "specify the group policy in the flavor extra_spec. If it is OK "
            "to let these groups be satisfied by overlapping resource "
            "providers then use 'group_policy': 'none'. If you want each "
            "group to be satisfied from a separate resource provider then "
            "use 'group_policy': 'isolate'.")

        if res_req.numbered_groups_from_flavor <= 1:
            LOG.info(
                "At least one numbered request group is defined outside of "
                "the flavor (e.g. in a port that has a QoS minimum bandwidth "
                "policy rule attached) but the flavor did not specify any "
                "group policy. To avoid the placement failure nova defaults "
                "the group policy to 'none'.")
            res_req.group_policy = 'none'

    return res_req


# TODO(mriedem): Remove this when select_destinations() in the scheduler takes
# some sort of skip_filters flag.
def claim_resources_on_destination(
        context, reportclient, instance, source_node, dest_node,
        source_allocations=None, consumer_generation=None):
    """Copies allocations from source node to dest node in Placement

    Normally the scheduler will allocate resources on a chosen destination
    node during a move operation like evacuate and live migration. However,
    because of the ability to force a host and bypass the scheduler, this
    method can be used to manually copy allocations from the source node to
    the forced destination node.

    This is only appropriate when the instance flavor on the source node
    is the same on the destination node, i.e. don't use this for resize.

    :param context: The request context.
    :param reportclient: An instance of the SchedulerReportClient.
    :param instance: The instance being moved.
    :param source_node: source ComputeNode where the instance currently
                        lives
    :param dest_node: destination ComputeNode where the instance is being
                      moved
    :param source_allocations: The consumer's current allocations on the
                               source compute
    :param consumer_generation: The expected generation of the consumer.
                                None if a new consumer is expected
    :raises NoValidHost: If the allocation claim on the destination
                         node fails.
    :raises: keystoneauth1.exceptions.base.ClientException on failure to
             communicate with the placement API
    :raises: ConsumerAllocationRetrievalFailed if the placement API call fails
    :raises: AllocationUpdateFailed: If a parallel consumer update changed the
                                     consumer
    """
    # Get the current allocations for the source node and the instance.
    # NOTE(gibi) For the live migrate case, the caller provided the
    # allocation that needs to be used on the dest_node along with the
    # expected consumer_generation of the consumer (which is the instance).
    if not source_allocations:
        # NOTE(gibi): This is the forced evacuate case where the caller did not
        # provide any allocation request. So we ask placement here for the
        # current allocation and consumer generation and use that for the new
        # allocation on the dest_node. If the allocation fails due to consumer
        # generation conflict then the claim will raise and the operation will
        # be aborted.
        # NOTE(gibi): This only detect a small portion of possible
        # cases when allocation is modified outside of the this
        # code path. The rest can only be detected if nova would
        # cache at least the consumer generation of the instance.
        allocations = reportclient.get_allocs_for_consumer(
            context, instance.uuid)
        source_allocations = allocations.get('allocations', {})
        consumer_generation = allocations.get('consumer_generation')

        if not source_allocations:
            # This shouldn't happen, so just raise an error since we cannot
            # proceed.
            raise exception.ConsumerAllocationRetrievalFailed(
                consumer_uuid=instance.uuid,
                error=_(
                    'Expected to find allocations for source node resource '
                    'provider %s. Retry the operation without forcing a '
                    'destination host.') % source_node.uuid)

    # Generate an allocation request for the destination node.
    # NOTE(gibi): if the source allocation allocates from more than one RP
    # then we need to fail as the dest allocation might also need to be
    # complex (e.g. nested) and we cannot calculate that allocation request
    # properly without a placement allocation candidate call.
    # Alternatively we could sum up the source allocation and try to
    # allocate that from the root RP of the dest host. It would only work
    # if the dest host would not require nested allocation for this server
    # which is really a rare case.
    if len(source_allocations) > 1:
        reason = (_('Unable to move instance %(instance_uuid)s to '
                    'host %(host)s. The instance has complex allocations '
                    'on the source host so move cannot be forced.') %
                  {'instance_uuid': instance.uuid,
                   'host': dest_node.host})
        raise exception.NoValidHost(reason=reason)
    alloc_request = {
        'allocations': {
            dest_node.uuid: {
                'resources':
                    source_allocations[source_node.uuid]['resources']}
        },
    }
    # import locally to avoid cyclic import
    from nova.scheduler.client import report
    # The claim_resources method will check for existing allocations
    # for the instance and effectively "double up" the allocations for
    # both the source and destination node. That's why when requesting
    # allocations for resources on the destination node before we move,
    # we use the existing resource allocations from the source node.
    if reportclient.claim_resources(
            context, instance.uuid, alloc_request,
            instance.project_id, instance.user_id,
            allocation_request_version=report.CONSUMER_GENERATION_VERSION,
            consumer_generation=consumer_generation):
        LOG.debug('Instance allocations successfully created on '
                  'destination node %(dest)s: %(alloc_request)s',
                  {'dest': dest_node.uuid,
                   'alloc_request': alloc_request},
                  instance=instance)
    else:
        # We have to fail even though the user requested that we force
        # the host. This is because we need Placement to have an
        # accurate reflection of what's allocated on all nodes so the
        # scheduler can make accurate decisions about which nodes have
        # capacity for building an instance.
        reason = (_('Unable to move instance %(instance_uuid)s to '
                    'host %(host)s. There is not enough capacity on '
                    'the host for the instance.') %
                  {'instance_uuid': instance.uuid,
                   'host': dest_node.host})
        raise exception.NoValidHost(reason=reason)


def set_vm_state_and_notify(context, instance_uuid, service, method, updates,
                            ex, request_spec):
    """Updates the instance, sets the fault and sends an error notification.

    :param context: The request context.
    :param instance_uuid: The UUID of the instance to update.
    :param service: The name of the originating service, e.g. 'compute_task'.
        This becomes part of the publisher_id for the notification payload.
    :param method: The method that failed, e.g. 'migrate_server'.
    :param updates: dict of updates for the instance object, typically a
        vm_state and/or task_state value.
    :param ex: An exception which occurred during the given method.
    :param request_spec: Optional request spec.
    """
    # e.g. "Failed to compute_task_migrate_server: No valid host was found"
    LOG.warning("Failed to %(service)s_%(method)s: %(ex)s",
                {'service': service, 'method': method, 'ex': ex})

    # Convert the request spec to a dict if needed.
    if request_spec is not None:
        if isinstance(request_spec, objects.RequestSpec):
            request_spec = request_spec.to_legacy_request_spec_dict()
    else:
        request_spec = {}

    vm_state = updates['vm_state']
    properties = request_spec.get('instance_properties', {})
    notifier = rpc.get_notifier(service)
    state = vm_state.upper()
    LOG.warning('Setting instance to %s state.', state,
                instance_uuid=instance_uuid)

    instance = objects.Instance(context=context, uuid=instance_uuid,
                                **updates)
    instance.obj_reset_changes(['uuid'])
    instance.save()
    compute_utils.add_instance_fault_from_exc(
        context, instance, ex, sys.exc_info())

    payload = dict(request_spec=request_spec,
                   instance_properties=properties,
                   instance_id=instance_uuid,
                   state=vm_state,
                   method=method,
                   reason=ex)

    event_type = '%s.%s' % (service, method)
    notifier.error(context, event_type, payload)
    compute_utils.notify_about_compute_task_error(
        context, method, instance_uuid, request_spec, vm_state, ex,
        traceback.format_exc())


def build_filter_properties(scheduler_hints, forced_host,
        forced_node, instance_type):
    """Build the filter_properties dict from data in the boot request."""
    filter_properties = dict(scheduler_hints=scheduler_hints)
    filter_properties['instance_type'] = instance_type
    # TODO(alaski): It doesn't seem necessary that these are conditionally
    # added.  Let's just add empty lists if not forced_host/node.
    if forced_host:
        filter_properties['force_hosts'] = [forced_host]
    if forced_node:
        filter_properties['force_nodes'] = [forced_node]
    return filter_properties


def populate_filter_properties(filter_properties, selection):
    """Add additional information to the filter properties after a node has
    been selected by the scheduling process.
    """
    if isinstance(selection, dict):
        # TODO(edleafe): remove support for dicts
        host = selection['host']
        nodename = selection['nodename']
        limits = selection['limits']
    else:
        host = selection.service_host
        nodename = selection.nodename
        # Need to convert SchedulerLimits object to older dict format.
        if "limits" in selection and selection.limits is not None:
            limits = selection.limits.to_dict()
        else:
            limits = {}
    # Adds a retry entry for the selected compute host and node:
    _add_retry_host(filter_properties, host, nodename)

    # Adds oversubscription policy
    if not filter_properties.get('force_hosts'):
        filter_properties['limits'] = limits


def populate_retry(filter_properties, instance_uuid):
    max_attempts = CONF.scheduler.max_attempts
    force_hosts = filter_properties.get('force_hosts', [])
    force_nodes = filter_properties.get('force_nodes', [])

    # In the case of multiple force hosts/nodes, scheduler should not
    # disable retry filter but traverse all force hosts/nodes one by
    # one till scheduler gets a valid target host.
    if (max_attempts == 1 or len(force_hosts) == 1 or len(force_nodes) == 1):
        # re-scheduling is disabled, log why
        if max_attempts == 1:
            LOG.debug('Re-scheduling is disabled due to "max_attempts" config')
        else:
            LOG.debug("Re-scheduling is disabled due to forcing a host (%s) "
                      "and/or node (%s)", force_hosts, force_nodes)
        return

    # retry is enabled, update attempt count:
    retry = filter_properties.setdefault(
        'retry', {
            'num_attempts': 0,
            'hosts': []  # list of compute hosts tried
    })
    retry['num_attempts'] += 1

    _log_compute_error(instance_uuid, retry)
    exc_reason = retry.pop('exc_reason', None)

    if retry['num_attempts'] > max_attempts:
        msg = (_('Exceeded max scheduling attempts %(max_attempts)d '
                 'for instance %(instance_uuid)s. '
                 'Last exception: %(exc_reason)s')
               % {'max_attempts': max_attempts,
                  'instance_uuid': instance_uuid,
                  'exc_reason': exc_reason})
        raise exception.MaxRetriesExceeded(reason=msg)


def _log_compute_error(instance_uuid, retry):
    """If the request contained an exception from a previous compute
    build/resize operation, log it to aid debugging
    """
    exc = retry.get('exc')  # string-ified exception from compute
    if not exc:
        return  # no exception info from a previous attempt, skip

    hosts = retry.get('hosts', None)
    if not hosts:
        return  # no previously attempted hosts, skip

    last_host, last_node = hosts[-1]
    LOG.error(
        'Error from last host: %(last_host)s (node %(last_node)s): %(exc)s',
        {'last_host': last_host, 'last_node': last_node, 'exc': exc},
        instance_uuid=instance_uuid)


def _add_retry_host(filter_properties, host, node):
    """Add a retry entry for the selected compute node. In the event that
    the request gets re-scheduled, this entry will signal that the given
    node has already been tried.
    """
    retry = filter_properties.get('retry', None)
    if not retry:
        return
    hosts = retry['hosts']
    hosts.append([host, node])


def parse_options(opts, sep='=', converter=str, name=""):
    """Parse a list of options, each in the format of <key><sep><value>. Also
    use the converter to convert the value into desired type.

    :params opts: list of options, e.g. from oslo_config.cfg.ListOpt
    :params sep: the separator
    :params converter: callable object to convert the value, should raise
                       ValueError for conversion failure
    :params name: name of the option

    :returns: a lists of tuple of values (key, converted_value)
    """
    good = []
    bad = []
    for opt in opts:
        try:
            key, seen_sep, value = opt.partition(sep)
            value = converter(value)
        except ValueError:
            key = None
            value = None
        if key and seen_sep and value is not None:
            good.append((key, value))
        else:
            bad.append(opt)
    if bad:
        LOG.warning("Ignoring the invalid elements of the option "
                    "%(name)s: %(options)s",
                    {'name': name, 'options': ", ".join(bad)})
    return good


def validate_filter(filter):
    """Validates that the filter is configured in the default filters."""
    return filter in CONF.filter_scheduler.enabled_filters


def validate_weigher(weigher):
    """Validates that the weigher is configured in the default weighers."""
    weight_classes = CONF.filter_scheduler.weight_classes
    if 'nova.scheduler.weights.all_weighers' in weight_classes:
        return True
    return weigher in weight_classes


_SUPPORTS_AFFINITY = None
_SUPPORTS_ANTI_AFFINITY = None
_SUPPORTS_SOFT_AFFINITY = None
_SUPPORTS_SOFT_ANTI_AFFINITY = None


def _get_group_details(context, instance_uuid, user_group_hosts=None):
    """Provide group_hosts and group_policies sets related to instances if
    those instances are belonging to a group and if corresponding filters are
    enabled.

    :param instance_uuid: UUID of the instance to check
    :param user_group_hosts: Hosts from the group or empty set

    :returns: None or namedtuple GroupDetails
    """
    global _SUPPORTS_AFFINITY
    if _SUPPORTS_AFFINITY is None:
        _SUPPORTS_AFFINITY = validate_filter(
            'ServerGroupAffinityFilter')
    global _SUPPORTS_ANTI_AFFINITY
    if _SUPPORTS_ANTI_AFFINITY is None:
        _SUPPORTS_ANTI_AFFINITY = validate_filter(
            'ServerGroupAntiAffinityFilter')
    global _SUPPORTS_SOFT_AFFINITY
    if _SUPPORTS_SOFT_AFFINITY is None:
        _SUPPORTS_SOFT_AFFINITY = validate_weigher(
            'nova.scheduler.weights.affinity.ServerGroupSoftAffinityWeigher')
    global _SUPPORTS_SOFT_ANTI_AFFINITY
    if _SUPPORTS_SOFT_ANTI_AFFINITY is None:
        _SUPPORTS_SOFT_ANTI_AFFINITY = validate_weigher(
            'nova.scheduler.weights.affinity.'
            'ServerGroupSoftAntiAffinityWeigher')

    if not instance_uuid:
        return

    try:
        group = objects.InstanceGroup.get_by_instance_uuid(context,
                                                           instance_uuid)
    except exception.InstanceGroupNotFound:
        return

    policies = set(('anti-affinity', 'affinity', 'soft-affinity',
                    'soft-anti-affinity'))
    if group.policy in policies:
        if not _SUPPORTS_AFFINITY and 'affinity' == group.policy:
            msg = _("ServerGroupAffinityFilter not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        if not _SUPPORTS_ANTI_AFFINITY and 'anti-affinity' == group.policy:
            msg = _("ServerGroupAntiAffinityFilter not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        if (not _SUPPORTS_SOFT_AFFINITY and 'soft-affinity' == group.policy):
            msg = _("ServerGroupSoftAffinityWeigher not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        if (not _SUPPORTS_SOFT_ANTI_AFFINITY and
                'soft-anti-affinity' == group.policy):
            msg = _("ServerGroupSoftAntiAffinityWeigher not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        group_hosts = set(group.get_hosts())
        user_hosts = set(user_group_hosts) if user_group_hosts else set()
        return GroupDetails(hosts=user_hosts | group_hosts,
                            policy=group.policy, members=group.members)


def _get_instance_group_hosts_all_cells(context, instance_group):
    def get_hosts_in_cell(cell_context):
        # NOTE(melwitt): The obj_alternate_context is going to mutate the
        # cell_instance_group._context and to do this in a scatter-gather
        # with multiple parallel greenthreads, we need the instance groups
        # to be separate object copies.
        cell_instance_group = instance_group.obj_clone()
        with cell_instance_group.obj_alternate_context(cell_context):
            return cell_instance_group.get_hosts()

    results = nova_context.scatter_gather_skip_cell0(context,
                                                     get_hosts_in_cell)
    hosts = []
    for result in results.values():
        # TODO(melwitt): We will need to handle scenarios where an exception
        # is raised while targeting a cell and when a cell does not respond
        # as part of the "handling of a down cell" spec:
        # https://blueprints.launchpad.net/nova/+spec/handling-down-cell
        if not nova_context.is_cell_failure_sentinel(result):
            hosts.extend(result)
    return hosts


def setup_instance_group(context, request_spec):
    """Add group_hosts and group_policies fields to filter_properties dict
    based on instance uuids provided in request_spec, if those instances are
    belonging to a group.

    :param request_spec: Request spec
    """
    # NOTE(melwitt): Proactively query for the instance group hosts instead of
    # relying on a lazy-load via the 'hosts' field of the InstanceGroup object.
    if (request_spec.instance_group and
            'hosts' not in request_spec.instance_group):
        group = request_spec.instance_group
        # If the context is already targeted to a cell (during a move
        # operation), we don't need to scatter-gather. We do need to use
        # obj_alternate_context here because the RequestSpec is queried at the
        # start of a move operation in compute/api, before the context has been
        # targeted.
        if context.db_connection:
            with group.obj_alternate_context(context):
                group.hosts = group.get_hosts()
        else:
            group.hosts = _get_instance_group_hosts_all_cells(context, group)

    if request_spec.instance_group and request_spec.instance_group.hosts:
        group_hosts = request_spec.instance_group.hosts
    else:
        group_hosts = None
    instance_uuid = request_spec.instance_uuid
    # This queries the group details for the group where the instance is a
    # member. The group_hosts passed in are the hosts that contain members of
    # the requested instance group.
    group_info = _get_group_details(context, instance_uuid, group_hosts)
    if group_info is not None:
        request_spec.instance_group.hosts = list(group_info.hosts)
        request_spec.instance_group.policy = group_info.policy
        request_spec.instance_group.members = group_info.members


def request_is_rebuild(spec_obj):
    """Returns True if request is for a rebuild.

    :param spec_obj: An objects.RequestSpec to examine (or None).
    """
    if not spec_obj:
        return False
    if 'scheduler_hints' not in spec_obj:
        return False
    check_type = spec_obj.scheduler_hints.get('_nova_check_type')
    return check_type == ['rebuild']


def claim_resources(ctx, client, spec_obj, instance_uuid, alloc_req,
        allocation_request_version=None):
    """Given an instance UUID (representing the consumer of resources) and the
    allocation_request JSON object returned from Placement, attempt to claim
    resources for the instance in the placement API. Returns True if the claim
    process was successful, False otherwise.

    :param ctx: The RequestContext object
    :param client: The scheduler client to use for making the claim call
    :param spec_obj: The RequestSpec object - needed to get the project_id
    :param instance_uuid: The UUID of the consuming instance
    :param alloc_req: The allocation_request received from placement for the
                      resources we want to claim against the chosen host. The
                      allocation_request satisfies the original request for
                      resources and can be supplied as-is (along with the
                      project and user ID to the placement API's PUT
                      /allocations/{consumer_uuid} call to claim resources for
                      the instance
    :param allocation_request_version: The microversion used to request the
                                       allocations.
    """
    if request_is_rebuild(spec_obj):
        # NOTE(danms): This is a rebuild-only scheduling request, so we should
        # not be doing any extra claiming
        LOG.debug('Not claiming resources in the placement API for '
                  'rebuild-only scheduling of instance %(uuid)s',
                  {'uuid': instance_uuid})
        return True

    LOG.debug("Attempting to claim resources in the placement API for "
              "instance %s", instance_uuid)

    project_id = spec_obj.project_id

    # We didn't start storing the user_id in the RequestSpec until Rocky so
    # if it's not set on an old RequestSpec, use the user_id from the context.
    if 'user_id' in spec_obj and spec_obj.user_id:
        user_id = spec_obj.user_id
    else:
        # FIXME(mriedem): This would actually break accounting if we relied on
        # the allocations for something like counting quota usage because in
        # the case of migrating or evacuating an instance, the user here is
        # likely the admin, not the owner of the instance, so the allocation
        # would be tracked against the wrong user.
        user_id = ctx.user_id

    # NOTE(gibi): this could raise AllocationUpdateFailed which means there is
    # a serious issue with the instance_uuid as a consumer. Every caller of
    # utils.claim_resources() assumes that instance_uuid will be a new consumer
    # and therefore we passing None as expected consumer_generation to
    # reportclient.claim_resources() here. If the claim fails
    # due to consumer generation conflict, which in this case means the
    # consumer is not new, then we let the AllocationUpdateFailed propagate and
    # fail the build / migrate as the instance is in inconsistent state.
    return client.claim_resources(ctx, instance_uuid, alloc_req, project_id,
            user_id, allocation_request_version=allocation_request_version,
            consumer_generation=None)


def get_weight_multiplier(host_state, multiplier_name, multiplier_config):
    """Given a HostState object, multplier_type name and multiplier_config,
    returns the weight multiplier.

    It reads the "multiplier_name" from "aggregate metadata" in host_state
    to override the multiplier_config. If the aggregate metadata doesn't
    contain the multiplier_name, the multiplier_config will be returned
    directly.

    :param host_state: The HostState object, which contains aggregate metadata
    :param multiplier_name: The weight multiplier name, like
           "cpu_weight_multiplier".
    :param multiplier_config: The weight multiplier configuration value
    """
    aggregate_vals = filters_utils.aggregate_values_from_key(host_state,
                                                             multiplier_name)
    try:
        value = filters_utils.validate_num_values(
            aggregate_vals, multiplier_config, cast_to=float)
    except ValueError as e:
        LOG.warning("Could not decode '%(name)s' weight multiplier: %(exce)s",
                    {'exce': e, 'name': multiplier_name})
        value = multiplier_config

    return value


def fill_provider_mapping(
        context, report_client, request_spec, host_selection):
    """Fills out the request group - resource provider mapping in the
    request spec.

    This is a workaround as placement does not return which RP
    fulfills which granular request group in the allocation candidate
    request. There is a spec proposing a solution in placement:
    https://review.opendev.org/#/c/597601/
    When that spec is implemented then this function can be
    replaced with a simpler code that copies the group - RP
    mapping out from the Selection object returned by the scheduler's
    select_destinations call.

    :param context: The security context
    :param report_client: SchedulerReportClient instance to be used to
        communicate with placement
    :param request_spec: The RequestSpec object associated with the
        operation
    :param host_selection: The Selection object returned by the scheduler
        for this operation
    """
    # Exit early if this request spec does not require mappings.
    if not request_spec.maps_requested_resources:
        return

    # Technically out-of-tree scheduler drivers can still not create
    # allocations in placement but if request_spec.maps_requested_resources
    # is not empty and the scheduling succeeded then placement has to be
    # involved
    ar = jsonutils.loads(host_selection.allocation_request)
    allocs = ar['allocations']

    fill_provider_mapping_based_on_allocation(
        context, report_client, request_spec, allocs)


def fill_provider_mapping_based_on_allocation(
        context, report_client, request_spec, allocation):
    """Fills out the request group - resource provider mapping in the
    request spec based on the current allocation of the instance.

    The fill_provider_mapping() variant is expected to be called in every
    scenario when a Selection object is available from the scheduler. However
    in case of revert operations such Selection does not exists. In this case
    the mapping is calculated based on the allocation of the source host the
    move operation is reverting to.

    :param context: The security context
    :param report_client: SchedulerReportClient instance to be used to
        communicate with placement
    :param request_spec: The RequestSpec object associated with the
        operation
    :param allocation: allocation dict of the instance, keyed by RP UUID.
    """

    # Exit early if this request spec does not require mappings.
    if not request_spec.maps_requested_resources:
        return

    # NOTE(gibi): Getting traits from placement for each instance in a
    # instance multi-create scenario is unnecessarily expensive. But
    # instance multi-create cannot be used with pre-created neutron ports
    # and this code can only be triggered with such pre-created ports so
    # instance multi-create is not an issue. If this ever become an issue
    # in the future then we could stash the RP->traits mapping on the
    # Selection object since we can pull the traits for each provider from
    # the GET /allocation_candidates response in the scheduler (or leverage
    # the change from the spec mentioned in the docstring above).
    provider_traits = {
        rp_uuid: report_client.get_provider_traits(
            context, rp_uuid).traits
        for rp_uuid in allocation}
    # NOTE(gibi): The allocation dict is in the format of the PUT /allocations
    # and that format can change. The current format can be detected from
    # allocation_request_version key of the Selection object.
    request_spec.map_requested_resources_to_providers(
        allocation, provider_traits)
