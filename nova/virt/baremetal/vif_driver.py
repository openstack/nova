# Copyright (c) 2012 NTT DOCOMO, INC.
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

from nova import context
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.baremetal import db as bmdb

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class BareMetalVIFDriver(object):

    def _after_plug(self, instance, vif, pif):
        pass

    def _after_unplug(self, instance, vif, pif):
        pass

    def plug(self, instance, vif):
        LOG.debug(_("plug: instance_uuid=%(uuid)s vif=%(vif)s")
                  % {'uuid': instance['uuid'], 'vif': vif})
        vif_uuid = vif['id']
        ctx = context.get_admin_context()
        node = bmdb.bm_node_get_by_instance_uuid(ctx, instance['uuid'])

        # TODO(deva): optimize this database query
        #             this is just searching for a free physical interface
        pifs = bmdb.bm_interface_get_all_by_bm_node_id(ctx, node['id'])
        for pif in pifs:
            if not pif['vif_uuid']:
                bmdb.bm_interface_set_vif_uuid(ctx, pif['id'], vif_uuid)
                LOG.debug(_("pif:%(id)s is plugged (vif_uuid=%(vif_uuid)s)")
                          % {'id': pif['id'], 'vif_uuid': vif_uuid})
                self._after_plug(instance, vif, pif)
                return

        # NOTE(deva): should this really be raising an exception
        #             when there are no physical interfaces left?
        raise exception.NovaException(_(
                "Baremetal node: %(id)s has no available physical interface"
                " for virtual interface %(vif_uuid)s")
                % {'id': node['id'], 'vif_uuid': vif_uuid})

    def unplug(self, instance, vif):
        LOG.debug(_("unplug: instance_uuid=%(uuid)s vif=%(vif)s"),
                  {'uuid': instance['uuid'], 'vif': vif})
        vif_uuid = vif['id']
        ctx = context.get_admin_context()
        try:
            pif = bmdb.bm_interface_get_by_vif_uuid(ctx, vif_uuid)
            bmdb.bm_interface_set_vif_uuid(ctx, pif['id'], None)
            LOG.debug(_("pif:%(id)s is unplugged (vif_uuid=%(vif_uuid)s)")
                      % {'id': pif['id'], 'vif_uuid': vif_uuid})
            self._after_unplug(instance, vif, pif)
        except exception.NovaException:
            LOG.warn(_("no pif for vif_uuid=%s") % vif_uuid)
