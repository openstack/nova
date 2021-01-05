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

import typing as ty

from nova import context as nova_context
from nova import objects


def get_machine_type(
    context: 'nova_context.RequestContext',
    instance_uuid: str,
) -> ty.Optional[str]:
    """Get the registered machine type of an instance

    :param context: Request context.
    :param instance_uuid: Instance UUID to check.
    :returns: The machine type or None.
    :raises: exception.InstanceNotFound, exception.InstanceMappingNotFound
    """
    im = objects.InstanceMapping.get_by_instance_uuid(context, instance_uuid)
    with nova_context.target_cell(context, im.cell_mapping) as cctxt:
        # NOTE(lyarwood): While we are after the value of 'hw_machine_type'
        # stored as an image metadata property this actually comes from the
        # system metadata of the instance so we need to add
        # expected_attrs=['system_metadata'] here.
        instance = objects.instance.Instance.get_by_uuid(
            cctxt, instance_uuid, expected_attrs=['system_metadata'])
        return instance.image_meta.properties.get('hw_machine_type')
