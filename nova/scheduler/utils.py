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
import sys

from oslo.config import cfg
from oslo.serialization import jsonutils

from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova import exception
from nova.i18n import _, _LE, _LW
from nova import notifications
from nova import objects
from nova.objects import base as obj_base
from nova.openstack.common import log as logging
from nova import rpc


LOG = logging.getLogger(__name__)

scheduler_opts = [
    cfg.IntOpt('scheduler_max_attempts',
               default=3,
               help='Maximum number of attempts to schedule an instance'),
    ]

CONF = cfg.CONF
CONF.register_opts(scheduler_opts)

CONF.import_opt('scheduler_default_filters', 'nova.scheduler.host_manager')

GroupDetails = collections.namedtuple('GroupDetails', ['hosts', 'policies'])


def build_request_spec(ctxt, image, instances, instance_type=None):
    """Build a request_spec for the scheduler.

    The request_spec assumes that all instances to be scheduled are the same
    type.
    """
    instance = instances[0]
    if isinstance(instance, obj_base.NovaObject):
        instance = obj_base.obj_to_primitive(instance)

    if instance_type is None:
        instance_type = flavors.extract_flavor(instance)
        # NOTE(danms): This won't have extra_specs, so fill in the gaps
        _instance_type = objects.Flavor.get_by_flavor_id(
            ctxt, instance_type['flavorid'])
        instance_type.extra_specs = instance_type.get('extra_specs', {})
        instance_type.extra_specs.update(_instance_type.extra_specs)

    if isinstance(instance_type, objects.Flavor):
        instance_type = obj_base.obj_to_primitive(instance_type)

    request_spec = {
            'image': image or {},
            'instance_properties': instance,
            'instance_type': instance_type,
            'num_instances': len(instances)}
    return jsonutils.to_primitive(request_spec)


def set_vm_state_and_notify(context, instance_uuid, service, method, updates,
                            ex, request_spec, db):
    """changes VM state and notifies."""
    LOG.warning(_LW("Failed to %(service)s_%(method)s: %(ex)s"),
                {'service': service, 'method': method, 'ex': ex})

    vm_state = updates['vm_state']
    properties = request_spec.get('instance_properties', {})
    # NOTE(vish): We shouldn't get here unless we have a catastrophic
    #             failure, so just set the instance to its internal state
    notifier = rpc.get_notifier(service)
    state = vm_state.upper()
    LOG.warning(_LW('Setting instance to %s state.'), state,
                instance_uuid=instance_uuid)

    # update instance state and notify on the transition
    # NOTE(hanlind): the send_update() call below is going to want to
    # know about the flavor, so we need to join the appropriate things
    # here and objectify the results.
    (old_ref, new_ref) = db.instance_update_and_get_original(
        context, instance_uuid, updates,
        columns_to_join=['system_metadata'])
    inst_obj = objects.Instance._from_db_object(
        context, objects.Instance(), new_ref,
        expected_attrs=['system_metadata'])
    notifications.send_update(context, old_ref, inst_obj, service=service)
    compute_utils.add_instance_fault_from_exc(context,
            new_ref, ex, sys.exc_info())

    payload = dict(request_spec=request_spec,
                    instance_properties=properties,
                    instance_id=instance_uuid,
                    state=vm_state,
                    method=method,
                    reason=ex)

    event_type = '%s.%s' % (service, method)
    notifier.error(context, event_type, payload)


def populate_filter_properties(filter_properties, host_state):
    """Add additional information to the filter properties after a node has
    been selected by the scheduling process.
    """
    if isinstance(host_state, dict):
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
    max_attempts = _max_attempts()
    force_hosts = filter_properties.get('force_hosts', [])
    force_nodes = filter_properties.get('force_nodes', [])

    if max_attempts == 1 or force_hosts or force_nodes:
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
    exc = retry.pop('exc', None)

    if retry['num_attempts'] > max_attempts:
        msg = (_('Exceeded max scheduling attempts %(max_attempts)d '
                 'for instance %(instance_uuid)s. '
                 'Last exception: %(exc)s')
               % {'max_attempts': max_attempts,
                  'instance_uuid': instance_uuid,
                  'exc': exc})
        raise exception.NoValidHost(reason=msg)


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


def _max_attempts():
    max_attempts = CONF.scheduler_max_attempts
    if max_attempts < 1:
        raise exception.NovaException(_("Invalid value for "
            "'scheduler_max_attempts', must be >= 1"))
    return max_attempts


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

    :params opts: list of options, e.g. from oslo.config.cfg.ListOpt
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
    return filter in CONF.scheduler_default_filters


_SUPPORTS_AFFINITY = None
_SUPPORTS_ANTI_AFFINITY = None


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
    _supports_server_groups = any((_SUPPORTS_AFFINITY,
                                   _SUPPORTS_ANTI_AFFINITY))
    if not _supports_server_groups or not instance_uuid:
        return

    try:
        group = objects.InstanceGroup.get_by_instance_uuid(context,
                                                           instance_uuid)
    except exception.InstanceGroupNotFound:
        return

    policies = set(('anti-affinity', 'affinity'))
    if any((policy in policies) for policy in group.policies):
        if (not _SUPPORTS_AFFINITY and 'affinity' in group.policies):
            msg = _("ServerGroupAffinityFilter not configured")
            LOG.error(msg)
            raise exception.NoValidHost(reason=msg)
        if (not _SUPPORTS_ANTI_AFFINITY and 'anti-affinity' in group.policies):
            msg = _("ServerGroupAntiAffinityFilter not configured")
            LOG.error(msg)
            raise exception.NoValidHost(reason=msg)
        group_hosts = set(group.get_hosts(context))
        user_hosts = set(user_group_hosts) if user_group_hosts else set()
        return GroupDetails(hosts=user_hosts | group_hosts,
                            policies=group.policies)


def setup_instance_group(context, request_spec, filter_properties):
    """Add group_hosts and group_policies fields to filter_properties dict
    based on instance uuids provided in request_spec, if those instances are
    belonging to a group.

    :param request_spec: Request spec
    :param filter_properties: Filter properties
    """
    group_hosts = filter_properties.get('group_hosts')
    # NOTE(sbauza) If there are multiple instance UUIDs, it's a boot
    # request and they will all be in the same group, so it's safe to
    # only check the first one.
    instance_uuid = request_spec.get('instance_properties', {}).get('uuid')
    group_info = _get_group_details(context, instance_uuid, group_hosts)
    if group_info is not None:
        filter_properties['group_updated'] = True
        filter_properties['group_hosts'] = group_info.hosts
        filter_properties['group_policies'] = group_info.policies
