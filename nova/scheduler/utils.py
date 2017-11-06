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
import functools
import re
import sys

from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils

from nova.api.openstack.placement import lib as placement_lib
from nova.compute import flavors
from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.i18n import _, _LE, _LW
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova.objects import instance as obj_instance
from nova import rpc


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

GroupDetails = collections.namedtuple('GroupDetails', ['hosts', 'policies',
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
                {"groupid": groupid, "val": amount})
            return
        self.get_request_group(groupid).resources[rclass] = amount

    def _add_trait(self, groupid, trait_name, trait_type):
        # Currently the only valid value for a trait entry is 'required'.
        trait_vals = ('required',)
        # Ensure the value is supported.
        if trait_type not in trait_vals:
            LOG.warning(
                "Only (%(tvals)s) traits are supported. Received '%(val)s' "
                "for key trait%(groupid)s.",
                {"tvals": ', '.join(trait_vals), "groupid": groupid,
                 "val": trait_type})
            return
        self.get_request_group(groupid).required_traits.add(trait_name)

    @classmethod
    def from_extra_specs(cls, extra_specs):
        """Processes resources and traits in numbered groupings in extra_specs.

        Examines extra_specs for items of the following forms:
            "resources:$RESOURCE_CLASS": $AMOUNT
            "resources$N:$RESOURCE_CLASS": $AMOUNT
            "trait:$TRAIT_NAME": "required"
            "trait$N:$TRAIT_NAME": "required"

        :param extra_specs: The flavor extra_specs dict.
        :return: A ResourceRequest object representing the resources and
                 required traits in the extra_specs.
        """
        ret = cls()
        for key, val in extra_specs.items():
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


def build_request_spec(ctxt, image, instances, instance_type=None):
    """Build a request_spec for the scheduler.

    The request_spec assumes that all instances to be scheduled are the same
    type.
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
    return jsonutils.to_primitive(request_spec)


def _process_extra_specs(extra_specs, resources):
    """Check the flavor's extra_specs for resource override information.
    These will be a dict that is generated from the flavor; and in the
    flavor, the extra_specs entries will be in the format of either:

        resources:$CUSTOM_RESOURCE_CLASS=$N
    ...to add a custom resource class to the request, with a positive
    integer amount of $N

        resources:$STANDARD_RESOURCE_CLASS=0
    ...to remove that resource class from the request.

        resources:$STANDARD_RESOURCE_CLASS=$N
    ...to add standard resource class (e.g. VGPU) to the request,
    or to override the flavor's value for that resource class with $N
    """
    resource_specs = {key.split("resources:", 1)[-1]: val
            for key, val in extra_specs.items()
            if key.startswith("resources:")}
    resource_keys = set(resource_specs)
    custom_keys = set([key for key in resource_keys
            if key.startswith(fields.ResourceClass.CUSTOM_NAMESPACE)])
    std_keys = resource_keys - custom_keys

    def validate_int(key):
        val = resource_specs.get(key)
        try:
            # Amounts must be integers
            return int(val)
        except ValueError:
            # Not a valid integer
            LOG.warning("Resource amounts must be integers. Received "
                    "'%(val)s' for key %(key)s.", {"key": key, "val": val})
            return None

    # Accept custom resource classes to be asked
    for custom_key in custom_keys:
        custom_val = validate_int(custom_key)
        if custom_val is not None:
            if custom_val == 0:
                # Custom resource values must be positive integers
                LOG.warning("Resource amounts must be positive integers. "
                        "Received '%(val)s' for key %(key)s.",
                        {"key": custom_key, "val": custom_val})
                continue
            resources[custom_key] = custom_val

    # Accept all standard resource classes to be overrided whether they exist
    # as flavor fields or not.
    for std_key in std_keys:
        if std_key not in set(resources).union(fields.ResourceClass.STANDARD):
            LOG.warning("Received an invalid ResourceClass '%(key)s' in "
                    "extra_specs.", {"key": std_key})
            continue
        val = validate_int(std_key)
        if val is None:
            # Received an invalid amount. It's already logged, so move on.
            continue
        elif val == 0:
            resources.pop(std_key, None)
        else:
            resources[std_key] = val


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
        _process_extra_specs(flavor.extra_specs, resources)
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
    """Given a RequestSpec object, returns a dict, keyed by resource class
    name, of requested amounts of those resources.
    """
    resources = {}

    resources[fields.ResourceClass.VCPU] = spec_obj.vcpus
    resources[fields.ResourceClass.MEMORY_MB] = spec_obj.memory_mb

    requested_disk_mb = (1024 * (spec_obj.root_gb +
                                 spec_obj.ephemeral_gb) +
                         spec_obj.swap)
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
        resources[fields.ResourceClass.DISK_GB] = requested_disk_gb
    if "extra_specs" in spec_obj.flavor:
        _process_extra_specs(spec_obj.flavor.extra_specs, resources)

    return resources


# TODO(mriedem): Remove this when select_destinations() in the scheduler takes
# some sort of skip_filters flag.
def claim_resources_on_destination(
        reportclient, instance, source_node, dest_node):
    """Copies allocations from source node to dest node in Placement

    Normally the scheduler will allocate resources on a chosen destination
    node during a move operation like evacuate and live migration. However,
    because of the ability to force a host and bypass the scheduler, this
    method can be used to manually copy allocations from the source node to
    the forced destination node.

    This is only appropriate when the instance flavor on the source node
    is the same on the destination node, i.e. don't use this for resize.

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
    source_node_allocations = (
        reportclient.get_allocations_for_consumer_by_provider(
            source_node.uuid, instance.uuid))
    if source_node_allocations:
        # Generate an allocation request for the destination node.
        alloc_request = {
            'allocations': [
                {
                    'resource_provider': {
                        'uuid': dest_node.uuid
                    },
                    'resources': source_node_allocations
                }
            ]
        }
        # The claim_resources method will check for existing allocations
        # for the instance and effectively "double up" the allocations for
        # both the source and destination node. That's why when requesting
        # allocations for resources on the destination node before we move,
        # we use the existing resource allocations from the source node.
        if reportclient.claim_resources(
                instance.uuid, alloc_request,
                instance.project_id, instance.user_id):
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


def populate_filter_properties(filter_properties, host_state):
    """Add additional information to the filter properties after a node has
    been selected by the scheduling process.
    """
    if isinstance(host_state, dict):
        # TODO(edleafe): remove support for dicts
        host = host_state['host']
        nodename = host_state['nodename']
        limits = host_state['limits']
    else:
        host = host_state.host
        nodename = host_state.nodename
        limits = host_state.limits

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
    LOG.error(_LE('Error from last host: %(last_host)s (node %(last_node)s):'
                  ' %(exc)s'),
              {'last_host': last_host,
               'last_node': last_node,
               'exc': exc},
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
        LOG.warning(_LW("Ignoring the invalid elements of the option "
                        "%(name)s: %(options)s"),
                    {'name': name,
                     'options': ", ".join(bad)})
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
    if any((policy in policies) for policy in group.policies):
        if not _SUPPORTS_AFFINITY and 'affinity' in group.policies:
            msg = _("ServerGroupAffinityFilter not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        if not _SUPPORTS_ANTI_AFFINITY and 'anti-affinity' in group.policies:
            msg = _("ServerGroupAntiAffinityFilter not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        if (not _SUPPORTS_SOFT_AFFINITY
                and 'soft-affinity' in group.policies):
            msg = _("ServerGroupSoftAffinityWeigher not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        if (not _SUPPORTS_SOFT_ANTI_AFFINITY
                and 'soft-anti-affinity' in group.policies):
            msg = _("ServerGroupSoftAntiAffinityWeigher not configured")
            LOG.error(msg)
            raise exception.UnsupportedPolicyException(reason=msg)
        group_hosts = set(group.get_hosts())
        user_hosts = set(user_group_hosts) if user_group_hosts else set()
        return GroupDetails(hosts=user_hosts | group_hosts,
                            policies=group.policies, members=group.members)


def setup_instance_group(context, request_spec):
    """Add group_hosts and group_policies fields to filter_properties dict
    based on instance uuids provided in request_spec, if those instances are
    belonging to a group.

    :param request_spec: Request spec
    """
    if request_spec.instance_group and request_spec.instance_group.hosts:
        group_hosts = request_spec.instance_group.hosts
    else:
        group_hosts = None
    instance_uuid = request_spec.instance_uuid
    group_info = _get_group_details(context, instance_uuid, group_hosts)
    if group_info is not None:
        request_spec.instance_group.hosts = list(group_info.hosts)
        request_spec.instance_group.policies = group_info.policies
        request_spec.instance_group.members = group_info.members


def retry_on_timeout(retries=1):
    """Retry the call in case a MessagingTimeout is raised.

    A decorator for retrying calls when a service dies mid-request.

    :param retries: Number of retries
    :returns: Decorator
    """
    def outer(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except messaging.MessagingTimeout:
                    attempt += 1
                    if attempt <= retries:
                        LOG.warning(_LW(
                            "Retrying %(name)s after a MessagingTimeout, "
                            "attempt %(attempt)s of %(retries)s."),
                                 {'attempt': attempt, 'retries': retries,
                                  'name': func.__name__})
                    else:
                        raise
        return wrapped
    return outer

retry_select_destinations = retry_on_timeout(CONF.scheduler.max_attempts - 1)
