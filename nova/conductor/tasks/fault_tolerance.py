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
from nova.compute import vm_states
from nova import exception
from nova import network
from nova import objects
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
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

    def _failover_network(self, context, p_instance, s_instance):
        p_nw_info = compute_utils.get_nw_info_for_instance(p_instance)
        # TODO(ORBIT): Multiple nics
        vif = p_nw_info[0]

        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(port_id=vif["id"])])

        self.network_api.deallocate_for_instance(
            context, p_instance, requested_networks=requested_networks)

        self.network_api.allocate_for_instance(
            context, s_instance, requested_networks=requested_networks)

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

            self._failover_network(context, p_instance, s_instance)
            self._failover_name(context, p_instance, s_instance)

            del s_instance.system_metadata['instance_type_extra_ft:secondary']
            s_instance.save()

            self.compute_api.delete(context, p_instance)

        relation.destroy()

    # TODO(ORBIT): This might come in handy if the secondary VM need different
    #              resources (more RAM?) than the primary VM.
    #              Right now, we just change the role in the extra_specs.
    def _get_secondary_flavor(self, flavor, primary_instance):
        flavor['extra_specs']['ft:secondary'] = '1'
        return flavor

    def create_secondary_instance(self, context, primary_instance, host):
        """Deploy a secondary instance."""

        LOG.debug("Attempting to deploy secondary instance for primary "
                  "instance: %s", primary_instance.uuid)

        flavor = flavors.get_flavor(primary_instance.instance_type_id)
        flavor = self._get_secondary_flavor(flavor, primary_instance)

        scheduler_hints = {}
        scheduler_hints['ft_secondary_host'] = dict(
            host=host['host'], nodename=host['nodename'], limits=host['limits']
        )

        (instances, _) = self.compute_api.create(
            context, flavor, primary_instance.get('image_ref'),
            display_name='FT-' + primary_instance.get('uuid'),
            display_description='Fault tolerance secondary instance',
            key_name=primary_instance.get('key_name'),
            metadata=primary_instance.get('metadata'),
            access_ip_v4=primary_instance.get('access_ip_v4'),
            access_ip_v6=primary_instance.get('access_ip_v6'),
            injected_files=None, # TODO
            admin_password=None, # TODO
            min_count=1,
            max_count=1,
            requested_networks=None, # TODO
            security_group=None, # TODO
            user_data=primary_instance.get('user_data'),
            availability_zone=primary_instance.get('availability_zone'),
            config_drive=primary_instance.get('config_drive'),
            block_device_mapping=None, # TODO
            auto_disk_config=primary_instance.get('auto_disk_config'),
            scheduler_hints=scheduler_hints,
            legacy_bdm=True, # TODO
            check_server_group_quota=False) # TODO

        secondary_instance = instances[0]

        relation = objects.FaultToleranceRelation()
        relation.primary_instance_uuid = primary_instance["uuid"]
        relation.secondary_instance_uuid = secondary_instance["uuid"]
        LOG.debug("Creating primary/secondary instance relation: %s", relation)
        relation.create(context)
