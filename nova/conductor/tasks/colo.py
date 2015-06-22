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

from oslo.config import cfg

import nova.context
from nova import db
from nova import exception
from nova import objects
from nova.openstack.common import log as logging

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

        system_metadata = instance.system_metadata
        if 'instance_type_extra_ft:secondary' in system_metadata:
            relation = (objects.FaultToleranceRelation.
                        get_by_secondary_instance_uuid(context, instance.uuid))
            primary_instance_uuid = relation.primary_instance_uuid
        else:
            primary_instance_uuid = instance.uuid

        # TODO(ORBIT): Handle COLONoVlanIdAvailable
        vlan_id = db.colo_allocate_vlan(context, primary_instance_uuid)

        LOG.debug("Got COLO VLAN ID %s for instance %s." % (vlan_id,
                                                            instance.uuid))

        return vlan_id
