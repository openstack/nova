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

from nova.compute import flavors
from nova import db
from nova.openstack.common import jsonutils


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
