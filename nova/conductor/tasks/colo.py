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

import time

from oslo.config import cfg

import nova.context
from nova.compute import power_state
from nova.compute import rpcapi as compute_rpcapi
from nova import db
from nova import exception
from nova import objects
from nova.openstack.common import log as logging
from nova import utils

CONF = cfg.CONF
CONF.register_opt(
    cfg.StrOpt('colo_vlan_range',
               default='100:200',
               help='The VLAN range used by COLO connections.')
)

LOG = logging.getLogger(__name__)

MIN_VLAN_TAG = 1
MAX_VLAN_TAG = 4094


class COLOTasks(object):

    def _parse_vlan_range(self):
        entry = CONF.colo_vlan_range.strip()
        try:
            vlan_min, vlan_max = entry.split(':')

            vlan_min = int(vlan_min)
            vlan_max = int(vlan_max)

            if not ((MIN_VLAN_TAG <= vlan_min <= MAX_VLAN_TAG) and
                    (MIN_VLAN_TAG <= vlan_max <= MAX_VLAN_TAG)):
                ex = (_("VLAN tags must be in the range of %d <= x <= %d") %
                      (MIN_VLAN_TAG, MAX_VLAN_TAG))
                raise exception.COLOVlanRangeError(vlan_range=entry, error=ex)

            return vlan_min, vlan_max
        except ValueError as ex:
            raise exception.COLOVlanRangeError(vlan_range=entry, error=ex)

    def sync_vlan_range(self):
        try:
            vlan_min, vlan_max = self._parse_vlan_range()
            context = nova.context.get_admin_context()

            LOG.debug("Syncing COLO VLAN range.")
            db.colo_sync_vlan_range(context, vlan_min, vlan_max)
        except exception.COLOVlanRangeError as e:
            LOG.error(e.format_message())

    def get_vlan_id(self, context, instance):
        LOG.debug("Acquiring COLO VLAN ID for instance %s." % instance.uuid)

        if utils.ft_secondary(instance):
            vlan_id = instance.system_metadata['instance_type_extra_ft:colo_vlan_id']
        else:
            # TODO(ORBIT): Handle COLONoVlanIdAvailable
            vlan_id = db.colo_allocate_vlan(context, instance.uuid)

        LOG.debug("Got COLO VLAN ID %s for instance %s." % (vlan_id,
                                                            instance.uuid))

        return vlan_id

    def _wait_for_instance_host(self, instance):
        i = 0
        while instance.power_state != power_state.PAUSED:
            LOG.debug("Waiting for instance to launch: %s status - %s",
                      instance.uuid,
                      power_state.STATE_MAP[instance.power_state])
            # TODO(ORBIT)
            i += 1
            if i > 100:
                raise Exception("COLO MIGRATE TIMEOUT")
            time.sleep(1)
            instance.refresh()

    def migrate(self, context, primary_instance, secondary_instance):
        for instance in (primary_instance, secondary_instance):
            instance.refresh()
            self._wait_for_instance_host(instance)
        LOG.debug("Starting COLO migration for %s.", primary_instance.uuid)
        compute_rpcapi.ComputeAPI().colo_migration(context, primary_instance,
                                                   secondary_instance)
