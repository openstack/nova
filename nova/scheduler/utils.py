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

import sys

from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova import db
from nova import notifications
from nova import notifier as notify
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def build_request_spec(ctxt, image, instances, instance_type=None):
    """Build a request_spec for the scheduler.

    The request_spec assumes that all instances to be scheduled are the same
    type.
    """
    instance = instances[0]
    if instance_type is None:
        instance_type = flavors.extract_flavor(instance)
    # NOTE(comstud): This is a bit ugly, but will get cleaned up when
    # we're passing an InstanceType internal object.
    extra_specs = db.flavor_extra_specs_get(ctxt,
                                                   instance_type['flavorid'])
    instance_type['extra_specs'] = extra_specs
    request_spec = {
            'image': image,
            'instance_properties': instance,
            'instance_type': instance_type,
            'num_instances': len(instances),
            # NOTE(alaski): This should be removed as logic moves from the
            # scheduler to conductor.  Provides backwards compatibility now.
            'instance_uuids': [inst['uuid'] for inst in instances]}
    return jsonutils.to_primitive(request_spec)


def set_vm_state_and_notify(context, service, method, updates, ex,
                            request_spec, db):
    """changes VM state and notifies."""
    LOG.warning(_("Failed to %(service)s_%(method)s: %(ex)s"),
                {'service': service, 'method': method, 'ex': ex})

    vm_state = updates['vm_state']
    properties = request_spec.get('instance_properties', {})
    # NOTE(vish): We shouldn't get here unless we have a catastrophic
    #             failure, so just set all instances to error. if uuid
    #             is not set, instance_uuids will be set to [None], this
    #             is solely to preserve existing behavior and can
    #             be removed along with the 'if instance_uuid:' if we can
    #             verify that uuid is always set.
    uuids = [properties.get('uuid')]
    from nova.conductor import api as conductor_api
    conductor = conductor_api.LocalAPI()
    notifier = notify.get_notifier(service)
    for instance_uuid in request_spec.get('instance_uuids') or uuids:
        if instance_uuid:
            state = vm_state.upper()
            LOG.warning(_('Setting instance to %s state.'), state,
                        instance_uuid=instance_uuid)

            # update instance state and notify on the transition
            (old_ref, new_ref) = db.instance_update_and_get_original(
                    context, instance_uuid, updates)
            notifications.send_update(context, old_ref, new_ref,
                    service=service)
            compute_utils.add_instance_fault_from_exc(context,
                    conductor,
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
    filter_properties['limits'] = limits


def _add_retry_host(filter_properties, host, node):
    """Add a retry entry for the selected compute node. In the event that
    the request gets re-scheduled, this entry will signal that the given
    node has already been tried.
    """
    retry = filter_properties.get('retry', None)
    force_hosts = filter_properties.get('force_hosts', [])
    force_nodes = filter_properties.get('force_nodes', [])
    if not retry or force_hosts or force_nodes:
        return
    hosts = retry['hosts']
    hosts.append([host, node])
