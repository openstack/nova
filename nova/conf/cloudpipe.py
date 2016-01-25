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

from nova.conf import paths
from nova.i18n import _

cloudpipe_opts = [
    cfg.StrOpt(
        'vpn_image_id',
        default='0',
        help=_('Image ID used when starting up a cloudpipe vpn server')),
    cfg.StrOpt(
        'vpn_flavor',
        default='m1.tiny',
        help=_('Flavor for vpn instances')),
    cfg.StrOpt(
        'boot_script_template',
        default=paths.basedir_def('nova/cloudpipe/bootscript.template'),
        help=_('Template for cloudpipe instance boot script')),
    cfg.StrOpt(
        'dmz_net',
        default='10.0.0.0',
        help=_('Network to push into openvpn config')),
    cfg.StrOpt(
        'dmz_mask',
        default='255.255.255.0',
        help=_('Netmask to push into openvpn config')),
    cfg.StrOpt(
        'vpn_key_suffix',
        default='-vpn',
        help=_('Suffix to add to project name for vpn key and secgroups'))
]


def register_opts(conf):
    conf.register_opts(cloudpipe_opts)


def list_opts():
    return {'DEFAULT': cloudpipe_opts}
