# Copyright (c) 2015 Umea University
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

from nova import compute
from nova.compute import flavors
from nova import objects

from nova.openstack.common import log as logging
LOG = logging.getLogger(__name__)


class FaultToleranceTasks(object):
    def __init__(self):
        self.compute_api = compute.API()

    def deploy_secondary_instance(self, context, primary_instance_uuid,
                                  host=None, node=None, limits=None,
                                  image=None, request_spec=None,
                                  filter_properties=None, admin_password=None,
                                  injected_files=None, requested_networks=None,
                                  security_groups=None,
                                  block_device_mapping=None, legacy_bdm=True):
        """Deploy a secondary instance."""

        LOG.debug("Attempting to deploy secondary instance for primary "
                  "instance: %s", primary_instance_uuid)

        primary_instance = self.compute_api.get(context, primary_instance_uuid)

        flavor = flavors.get_flavor(request_spec['instance_type']['id'])

        scheduler_hints = filter_properties.get('scheduler_hints') or {}
        scheduler_hints['ft_secondary_host'] = dict(
            host=host, nodename=node, limits=limits
        )

        (instances, _) = self.compute_api.create(
            context, flavor, image,
            display_name='FT-' + primary_instance.get('uuid'),
            display_description='Fault tolerance secondary instance',
            key_name=primary_instance.get('key_name'),
            metadata=primary_instance.get('metadata'),
            access_ip_v4=primary_instance.get('access_ip_v4'),
            access_ip_v6=primary_instance.get('access_ip_v6'),
            injected_files=injected_files,
            admin_password=admin_password,
            min_count=1,
            max_count=1,
            requested_networks=requested_networks,
            security_group=security_groups,
            user_data=primary_instance.get('user_data'),
            availability_zone=primary_instance.get('availability_zone'),
            config_drive=primary_instance.get('config_drive'),
            block_device_mapping=block_device_mapping,
            auto_disk_config=primary_instance.get('auto_disk_config'),
            scheduler_hints=scheduler_hints,
            legacy_bdm=legacy_bdm,
            # TODO
            check_server_group_quota=False)

        relation = objects.FaultToleranceRelation()
        relation.primary_instance_uuid = primary_instance.get('uuid')
        relation.secondary_instance_uuid = instances[0].uuid
        LOG.debug("Creating primary/secondary instance relation: %s", relation)
        relation.create(context)
