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
from nova.compute import utils as compute_utils
from nova import exception
from nova import network
from nova import objects
from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)


class FaultToleranceTasks(object):
    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()

    def _failover_name(self, context, p_instance, s_instance):
        s_instance.display_name = p_instance.display_name
        p_instance.display_name = 'FT-' + s_instance.uuid
        p_instance.save()
        s_instance.save()

    def _failover_floating_ip(self, context, p_instance, s_instance):
        p_nw_info = compute_utils.get_nw_info_for_instance(p_instance)
        s_nw_info = compute_utils.get_nw_info_for_instance(s_instance)
        floating_ips = p_nw_info[0].floating_ips()
        if floating_ips:
            # TODO(ORBIT): Multiple fixed/floating ips?
            floating_ip = floating_ips[0]
            fixed_ip = s_nw_info[0].fixed_ips()[0]
            self.network_api.associate_floating_ip(
                context, s_instance,
                floating_address=floating_ip['address'],
                fixed_address=fixed_ip['address'])

    def failover(self, context, instance_uuid):
        instance = self.compute_api.get(context, instance_uuid,
                                        want_objects=True)

        if not utils.ft_enabled(instance):
            raise exception.InstanceNotFaultTolerant(
                instance_uuid=instance_uuid)

        if utils.ft_secondary(instance):
            relation = objects.FaultToleranceRelation.\
                get_by_secondary_instance_uuid(context, instance.uuid)

            s_instance = instance
            p_instance = self.compute_api.get(context,
                                              relation.primary_instance_uuid,
                                              want_objects=True)

            self.compute_api.colo_failover(context, p_instance)

            self.compute_api.delete(context, s_instance)

            self.compute_api.colo_cleanup(context, p_instance)
        else:
            relations = objects.FaultToleranceRelationList.\
                    get_by_primary_instance_uuid(context, instance.uuid)

            # NOTE(ORBIT): Only one secondary instance supported.
            relation = relations[0]

            p_instance = instance
            s_instance = self.compute_api.get(context,
                                              relation.secondary_instance_uuid,
                                              want_objects=True)

            self.compute_api.colo_failover(context, s_instance)

            self._failover_floating_ip(context, p_instance, s_instance)
            self._failover_name(context, p_instance, s_instance)

            del s_instance.system_metadata['instance_type_extra_ft:secondary']
            s_instance.save()

        relation.destroy()

    # TODO(ORBIT): This might come in handy if the secondary VM need different
    #              resources (more RAM?) than the primary VM.
    #              Right now, we just change the role in the extra_specs.
    def _get_secondary_flavor(self, flavor):
        flavor['extra_specs']['ft:secondary'] = '1'
        return flavor

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
        flavor = self._get_secondary_flavor(flavor)

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
