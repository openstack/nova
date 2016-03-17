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

from oslo_config import cfg
from oslo_log import log as logging
import six.moves.urllib.parse as urlparse

from nova.i18n import _, _LW
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)

xenapi_torrent_opts = [
    cfg.StrOpt('torrent_base_url',
               help='Base URL for torrent files; must contain a slash'
                    ' character (see RFC 1808, step 6)'),
    cfg.FloatOpt('torrent_seed_chance',
                 default=1.0,
                 help='Probability that peer will become a seeder.'
                      ' (1.0 = 100%)'),
    cfg.IntOpt('torrent_seed_duration',
               default=3600,
               help='Number of seconds after downloading an image via'
                    ' BitTorrent that it should be seeded for other peers.'),
    cfg.IntOpt('torrent_max_last_accessed',
               default=86400,
               help='Cached torrent files not accessed within this number of'
                    ' seconds can be reaped'),
    cfg.IntOpt('torrent_listen_port_start',
               default=6881,
               min=1,
               max=65535,
               help='Beginning of port range to listen on'),
    cfg.IntOpt('torrent_listen_port_end',
               default=6891,
               min=1,
               max=65535,
               help='End of port range to listen on'),
    cfg.IntOpt('torrent_download_stall_cutoff',
               default=600,
               help='Number of seconds a download can remain at the same'
                    ' progress percentage w/o being considered a stall'),
    cfg.IntOpt('torrent_max_seeder_processes_per_host',
               default=1,
               help='Maximum number of seeder processes to run concurrently'
                    ' within a given dom0. (-1 = no limit)')
    ]

CONF = cfg.CONF
CONF.register_opts(xenapi_torrent_opts, 'xenserver')


class BittorrentStore(object):
    @staticmethod
    def _lookup_torrent_url_fn():
        """Load a "fetcher" func to get the right torrent URL.
        """

        if CONF.xenserver.torrent_base_url:
            if '/' not in CONF.xenserver.torrent_base_url:
                LOG.warning(_LW('Value specified in conf file for'
                             ' xenserver.torrent_base_url does not contain a'
                             ' slash character, therefore it will not be used'
                             ' as part of the torrent URL. Specify a valid'
                             ' base URL as defined by RFC 1808 (see step 6).'))

            def _default_torrent_url_fn(image_id):
                return urlparse.urljoin(CONF.xenserver.torrent_base_url,
                                        "%s.torrent" % image_id)

            return _default_torrent_url_fn

        raise RuntimeError(_('Cannot create default bittorrent URL'
                             ' without xenserver.torrent_base_url'
                             ' configuration option set.'))

    def download_image(self, context, session, instance, image_id):
        params = {}
        params['image_id'] = image_id
        params['uuid_stack'] = vm_utils._make_uuid_stack()
        params['sr_path'] = vm_utils.get_sr_path(session)
        params['torrent_seed_duration'] = CONF.xenserver.torrent_seed_duration
        params['torrent_seed_chance'] = CONF.xenserver.torrent_seed_chance
        params['torrent_max_last_accessed'] = \
                CONF.xenserver.torrent_max_last_accessed
        params['torrent_listen_port_start'] = \
                CONF.xenserver.torrent_listen_port_start
        params['torrent_listen_port_end'] = \
                CONF.xenserver.torrent_listen_port_end
        params['torrent_download_stall_cutoff'] = \
                CONF.xenserver.torrent_download_stall_cutoff
        params['torrent_max_seeder_processes_per_host'] = \
                CONF.xenserver.torrent_max_seeder_processes_per_host

        lookup_fn = self._lookup_torrent_url_fn()
        params['torrent_url'] = lookup_fn(image_id)

        vdis = session.call_plugin_serialized(
                'bittorrent', 'download_vhd', **params)

        return vdis

    def upload_image(self, context, session, instance, image_id, vdi_uuids):
        raise NotImplementedError
