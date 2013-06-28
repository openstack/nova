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
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier

LOG = logging.getLogger(__name__)


def build_request_spec(ctxt, image, instances):
    """Build a request_spec for the scheduler.

    The request_spec assumes that all instances to be scheduled are the same
    type.
    """
    instance = instances[0]
    instance_type = flavors.extract_flavor(instance)
    # NOTE(comstud): This is a bit ugly, but will get cleaned up when
    # we're passing an InstanceType internal object.
    extra_specs = db.instance_type_extra_specs_get(ctxt,
                                                   instance_type['flavorid'])
    instance_type['extra_specs'] = extra_specs
    request_spec = {
            'image': image,
            'instance_properties': instance,
            'instance_type': instance_type,
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
                    conductor_api.LocalAPI(),
                    new_ref, ex, sys.exc_info())

        payload = dict(request_spec=request_spec,
                        instance_properties=properties,
                        instance_id=instance_uuid,
                        state=vm_state,
                        method=method,
                        reason=ex)

        event_type = '%s.%s' % (service, method)
        notifier.notify(context, notifier.publisher_id(service),
                        event_type, notifier.ERROR, payload)
