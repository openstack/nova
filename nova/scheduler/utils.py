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

from oslo_log import log as logging
from oslo_serialization import jsonutils
from six.moves.urllib import parse

from nova.api.openstack.placement import lib as placement_lib
from nova.compute import flavors
from nova.compute import utils as compute_utils
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as obj_base
from nova.objects import instance as obj_instance
from nova import rc_fields as fields
from nova import rpc


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

    def __init__(self):
        # { ident: RequestGroup }
        self._rg_by_id = {}
        self._group_policy = None
        # Default to the configured limit but _limit can be
        # set to None to indicate "no limit".
        self._limit = CONF.scheduler.max_placement_results

    def __str__(self):
        return ', '.join(sorted(
            list(str(rg) for rg in list(self._rg_by_id.values()))))

    def get_request_group(self, ident):
        if ident not in self._rg_by_id:
            rq_grp = placement_lib.RequestGroup(use_same_provider=bool(ident))
            self._rg_by_id[ident] = rq_grp
        return self._rg_by_id[ident]

    def _add_resource(self, groupid, rclass, amount):
        # Validate the class.
        if not (rclass.startswith(fields.ResourceClass.CUSTOM_NAMESPACE) or
                        rclass in fields.ResourceClass.STANDARD):
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

    @classmethod
    def from_extra_specs(cls, extra_specs, req=None):
        """Processes resources and traits in numbered groupings in extra_specs.

        Examines extra_specs for items of the following forms:
            "resources:$RESOURCE_CLASS": $AMOUNT
            "resources$N:$RESOURCE_CLASS": $AMOUNT
            "trait:$TRAIT_NAME": "required"
            "trait$N:$TRAIT_NAME": "required"

        Does *not* yet handle member_of[$N].

        :param extra_specs: The flavor extra_specs dict.
        :param req: the ResourceRequest object to add the requirements to or
               None to create a new ResourceRequest
        :return: A ResourceRequest object representing the resources and
                 required traits in the extra_specs.
        """
        # TODO(efried): Handle member_of[$N], which will need to be reconciled
        # with destination.aggregates handling in resources_from_request_spec

        if req is not None:
            ret = req
        else:
            ret = cls()

        for key, val in extra_specs.items():
            if key == 'group_policy':
                ret._add_group_policy(val)
                continue

            match = cls.XS_KEYPAT.match(key)
            if not match:
                continue

            # 'prefix' is 'resources' or 'trait'
            # 'suffix' is $N or None
            # 'name' is either the resource class name or the trait name.
            prefix, suffix, name = match.groups()

            # Process "resources[$N]"
            if prefix == cls.XS_RES_PREFIX:
                ret._add_resource(suffix, name, val)

            # Process "trait[$N]"
            elif prefix == cls.XS_TRAIT_PREFIX:
                ret._add_trait(suffix, name, val)

        return ret

    @classmethod
    def from_image_props(cls, image_meta_props, req=None):
        """Processes image properties and adds trait requirements to the
           ResourceRequest

        :param image_meta_props: The ImageMetaProps object.
        :param req: the ResourceRequest object to add the requirements to or
               None to create a new ResourceRequest
        :return: A ResourceRequest object representing the required traits on
                the image.
        """
        if req is not None:
            ret = req
        else:
            ret = cls()

        if 'traits_required' in image_meta_props:
            for trait in image_meta_props.traits_required:
                # required traits from the image are always added to the
                # unnumbered request group, granular request groups are not
                # supported in image traits
                ret._add_trait(None, trait, "required")

        return ret

    def resource_groups(self):
        for rg in self._rg_by_id.values():
            yield rg.resources

    def merged_resources(self, flavor_resources=None):
        """Returns a merge of {resource_class: amount} for all resource groups.

        Amounts of the same resource class from different groups are added
        together.

        :param flavor_resources: A flat dict of {resource_class: amount}.  If
                                 specified, the resources therein are folded
                                 into the return dict, such that any resource
                                 in flavor_resources is included only if that
                                 resource class does not exist elsewhere in the
                                 merged ResourceRequest.
        :return: A dict of the form {resource_class: amount}
        """
        ret = collections.defaultdict(lambda: 0)
        for resource_dict in self.resource_groups():
            for resource_class, amount in resource_dict.items():
                ret[resource_class] += amount
        if flavor_resources:
            for resource_class, amount in flavor_resources.items():
                # If it's in there - even if zero - ignore the one from the
                # flavor.
                if resource_class not in ret:
                    ret[resource_class] = amount
            # Now strip zeros.  This has to be done after the above - we can't
            # use strip_zeros :(
            ret = {rc: amt for rc, amt in ret.items() if amt}
        return dict(ret)

    def _clean_empties(self):
        """Get rid of any empty ResourceGroup instances."""
        for ident, rg in list(self._rg_by_id.items()):
            if not any((rg.resources, rg.required_traits)):
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
        # NOTE(efried): The sorting herein is not necessary for the API; it is
        # to make testing easier and logging/debugging predictable.
        def to_queryparams(request_group, suffix):
            res = request_group.resources
            required_traits = request_group.required_traits
            forbidden_traits = request_group.forbidden_traits
            aggregates = request_group.member_of

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
    swap_in_gb = compute_utils.convert_mb_to_ceil_gb(flavor.swap)
    disk = ((0 if is_bfv else flavor.root_gb) +
            swap_in_gb + flavor.ephemeral_gb)

    resources = {
        fields.ResourceClass.VCPU: flavor.vcpus,
        fields.ResourceClass.MEMORY_MB: flavor.memory_mb,
        fields.ResourceClass.DISK_GB: disk,
    }
    if "extra_specs" in flavor:
        # TODO(efried): This method is currently only used from places that
        # assume the compute node is the only resource provider.  So for now,
        # we just merge together all the resources specified in the flavor and
        # pass them along.  This will need to be adjusted when nested and/or
        # shared RPs are in play.
        rreq = ResourceRequest.from_extra_specs(flavor.extra_specs)
        resources = rreq.merged_resources(flavor_resources=resources)

    return resources


def merge_resources(original_resources, new_resources, sign=1):
    """Merge a list of new resources with existing resources.

    Either add the resources (if sign is 1) or subtract (if sign is -1).
    If the resulting value is 0 do not include the resource in the results.
    """

    all_keys = set(original_resources.keys()) | set(new_resources.keys())
    for key in all_keys:
        value = (original_resources.get(key, 0) +
                 (sign * new_resources.get(key, 0)))
        if value:
            original_resources[key] = value
        else:
            original_resources.pop(key, None)


def resources_from_request_spec(spec_obj):
    """Given a RequestSpec object, returns a ResourceRequest of the resources,
    traits, and aggregates it represents.
    """
    spec_resources = {
        fields.ResourceClass.VCPU: spec_obj.vcpus,
        fields.ResourceClass.MEMORY_MB: spec_obj.memory_mb,
    }

    requested_disk_mb = ((1024 * spec_obj.ephemeral_gb) +
                         spec_obj.swap)

    if 'is_bfv' not in spec_obj or not spec_obj.is_bfv:
        # Either this is not a BFV instance, or we are not sure,
        # so ask for root_gb allocation
        requested_disk_mb += (1024 * spec_obj.root_gb)

    # NOTE(sbauza): Disk request is expressed in MB but we count
    # resources in GB. Since there could be a remainder of the division
    # by 1024, we need to ceil the result to the next bigger Gb so we
    # can be sure there would be enough disk space in the destination
    # to sustain the request.
    # FIXME(sbauza): All of that could be using math.ceil() but since
    # we support both py2 and py3, let's fake it until we only support
    # py3.
    requested_disk_gb = requested_disk_mb // 1024
    if requested_disk_mb % 1024 != 0:
        # Let's ask for a bit more space since we count in GB
        requested_disk_gb += 1
    # NOTE(sbauza): Some flavors provide zero size for disk values, we need
    # to avoid asking for disk usage.
    if requested_disk_gb != 0:
        spec_resources[fields.ResourceClass.DISK_GB] = requested_disk_gb

    # Process extra_specs
    if "extra_specs" in spec_obj.flavor:
        res_req = ResourceRequest.from_extra_specs(spec_obj.flavor.extra_specs)
        # If any of the three standard resources above was explicitly given in
        # the extra_specs - in any group - we need to replace it, or delete it
        # if it was given as zero.  We'll do this by grabbing a merged version
        # of the ResourceRequest resources and removing matching items from the
        # spec_resources.
        spec_resources = {rclass: amt for rclass, amt in spec_resources.items()
                          if rclass not in res_req.merged_resources()}
        # Now we don't need (or want) any remaining zero entries - remove them.
        res_req.strip_zeros()
    else:
        # Start with an empty one
        res_req = ResourceRequest()

    # Process any image properties
    if 'image' in spec_obj and 'properties' in spec_obj.image:
        res_req = ResourceRequest.from_image_props(spec_obj.image.properties,
                                                   req=res_req)

    # Add the (remaining) items from the spec_resources to the sharing group
    for rclass, amount in spec_resources.items():
        res_req.get_request_group(None).resources[rclass] = amount

    if 'requested_destination' in spec_obj:
        destination = spec_obj.requested_destination
        if destination and destination.aggregates:
            grp = res_req.get_request_group(None)
            grp.member_of = [tuple(ored.split(','))
                             for ored in destination.aggregates]

    # Don't limit allocation candidates when using force_hosts or force_nodes.
    if 'force_hosts' in spec_obj and spec_obj.force_hosts:
        res_req._limit = None
    if 'force_nodes' in spec_obj and spec_obj.force_nodes:
        res_req._limit = None

    return res_req


# TODO(mriedem): Remove this when select_destinations() in the scheduler takes
# some sort of skip_filters flag.
def claim_resources_on_destination(
        context, reportclient, instance, source_node, dest_node,
        source_node_allocations=None):
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
    :raises NoValidHost: If the allocation claim on the destination
                         node fails.
    """
    # Get the current allocations for the source node and the instance.
    if not source_node_allocations:
        source_node_allocations = (
            reportclient.get_allocations_for_consumer_by_provider(
                context, source_node.uuid, instance.uuid))
    if source_node_allocations:
        # Generate an allocation request for the destination node.
        alloc_request = {
            'allocations': {
                dest_node.uuid: {'resources': source_node_allocations}
            }
        }
        # The claim_resources method will check for existing allocations
        # for the instance and effectively "double up" the allocations for
        # both the source and destination node. That's why when requesting
        # allocations for resources on the destination node before we move,
        # we use the existing resource allocations from the source node.
        if reportclient.claim_resources(
                context, instance.uuid, alloc_request,
                instance.project_id, instance.user_id,
                allocation_request_version='1.12'):
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
            # capacity for building an instance. We also cannot rely on the
            # resource tracker in the compute service automatically healing
            # the allocations since that code is going away in Queens.
            reason = (_('Unable to move instance %(instance_uuid)s to '
                        'host %(host)s. There is not enough capacity on '
                        'the host for the instance.') %
                      {'instance_uuid': instance.uuid,
                       'host': dest_node.host})
            raise exception.NoValidHost(reason=reason)
    else:
        # This shouldn't happen, but it could be a case where there are
        # older (Ocata) computes still so the existing allocations are
        # getting overwritten by the update_available_resource periodic
        # task in the compute service.
        # TODO(mriedem): Make this an error when the auto-heal
        # compatibility code in the resource tracker is removed.
        LOG.warning('No instance allocations found for source node '
                    '%(source)s in Placement. Not creating allocations '
                    'for destination node %(dest)s and assuming the '
                    'compute service will heal the allocations.',
                    {'source': source_node.uuid, 'dest': dest_node.uuid},
                    instance=instance)


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
    # TODO(mriedem): Send a versioned notification.
    notifier.error(context, event_type, payload)


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
    if (max_attempts == 1 or len(force_hosts) == 1
                           or len(force_nodes) == 1):
        # re-scheduling is disabled.
        LOG.debug('Re-scheduling is disabled.')
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
        if (not _SUPPORTS_SOFT_ANTI_AFFINITY
                and 'soft-anti-affinity' == group.policy):
            msg = _("ServerGroupSoftAntiAffinityWeigher not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        # NOTE(melwitt): If the context is already targeted to a cell (during a
        # move operation), we don't need to scatter-gather.
        if context.db_connection:
            # We don't need to target the group object's context because it was
            # retrieved with the targeted context earlier in this method.
            group_hosts = set(group.get_hosts())
        else:
            group_hosts = set(_get_instance_group_hosts_all_cells(context,
                                                                  group))
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
        if result not in (nova_context.did_not_respond_sentinel,
                          nova_context.raised_exception_sentinel):
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

    # NOTE(jaypipes): So, the RequestSpec doesn't store the user_id,
    # only the project_id, so we need to grab the user information from
    # the context. Perhaps we should consider putting the user ID in
    # the spec object?
    user_id = ctx.user_id

    return client.claim_resources(ctx, instance_uuid, alloc_req, project_id,
            user_id, allocation_request_version=allocation_request_version)


def remove_allocation_from_compute(context, instance, compute_node_uuid,
                                   reportclient, flavor=None):
    """Removes the instance allocation from the compute host.

    :param context: The request context
    :param instance: the instance object owning the allocation
    :param compute_node_uuid: the UUID of the compute node where the allocation
                              needs to be removed
    :param reportclient: the SchedulerReportClient instances to be used to
                         communicate with Placement
    :param flavor: If provided then it is used to calculate the amount of
                   resource that needs to be removed. If not provided then
                   instance.flavor will be used
    :return: True if the removal was successful, False otherwise
    """

    if not flavor:
        flavor = instance.flavor

    my_resources = resources_from_flavor(instance, flavor)
    return reportclient.remove_provider_from_instance_allocation(
        context, instance.uuid, compute_node_uuid, instance.user_id,
        instance.project_id, my_resources)
