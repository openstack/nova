# Copyright 2013 OpenStack Foundation
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

from nova import exception
from nova.image import glance
import nova.openstack.common.log as logging
from nova.virt.xenapi import agent
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('glance_num_retries', 'nova.image.glance')


class GlanceStore(object):

    def upload_image(self, context, session, instance, vdi_uuids, image_id):
        """Requests that the Glance plugin bundle the specified VDIs and
        push them into Glance using the specified human-friendly name.
        """
        # NOTE(sirp): Currently we only support uploading images as VHD, there
        # is no RAW equivalent (yet)
        max_attempts = CONF.glance_num_retries + 1
        sleep_time = 0.5
        glance_api_servers = glance.get_api_servers()
        properties = {
            'auto_disk_config': instance['auto_disk_config'],
            'os_type': instance['os_type'] or CONF.default_os_type,
        }

        if agent.USE_AGENT_SM_KEY in instance["system_metadata"]:
            properties[agent.USE_AGENT_KEY] = \
                instance["system_metadata"][agent.USE_AGENT_SM_KEY]

        for attempt_num in xrange(1, max_attempts + 1):

            (glance_host,
             glance_port,
             glance_use_ssl) = glance_api_servers.next()

            try:

                params = {'vdi_uuids': vdi_uuids,
                          'image_id': image_id,
                          'glance_host': glance_host,
                          'glance_port': glance_port,
                          'glance_use_ssl': glance_use_ssl,
                          'sr_path': vm_utils.get_sr_path(session),
                          'auth_token': getattr(context, 'auth_token', None),
                          'properties': properties}

                LOG.debug(_("Asking xapi to upload to glance %(vdi_uuids)s as"
                            " ID %(image_id)s"
                            " glance server: %(glance_host)s:%(glance_port)d"
                            " attempt %(attempt_num)d/%(max_attempts)d"),
                          {'vdi_uuids': vdi_uuids,
                           'image_id': image_id,
                           'glance_host': glance_host,
                           'glance_port': glance_port,
                           'attempt_num': attempt_num,
                           'max_attempts': max_attempts}, instance=instance)

                return session.call_plugin_serialized('glance',
                                                      'upload_vhd',
                                                      **params)

            except session.XenAPI.Failure as exc:
                _type, _method, error = exc.details[:3]
                if error == 'RetryableError':
                    LOG.error(_('upload_vhd failed: %r') %
                              (exc.details[3:],))
                else:
                    raise
            time.sleep(sleep_time)
            sleep_time = min(2 * sleep_time, 15)

        raise exception.CouldNotUploadImage(image_id=image_id)
