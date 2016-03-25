# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
CloudPipe - Build a user-data payload zip file, and launch
an instance with it.

"""

import os
import string
import zipfile

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils

from nova import compute
from nova.compute import flavors
import nova.conf
from nova import crypto
from nova import db
from nova import exception
from nova.i18n import _
from nova import paths
from nova import utils


cloudpipe_opts = [
    cfg.StrOpt('vpn_image_id',
               default='0',
               help='Image ID used when starting up a cloudpipe vpn server'),
    cfg.StrOpt('vpn_flavor',
               default='m1.tiny',
               help=_('Flavor for vpn instances')),
    cfg.StrOpt('boot_script_template',
               default=paths.basedir_def('nova/cloudpipe/bootscript.template'),
               help=_('Template for cloudpipe instance boot script')),
    cfg.StrOpt('dmz_net',
               default='10.0.0.0',
               help=_('Network to push into openvpn config')),
    cfg.StrOpt('dmz_mask',
               default='255.255.255.0',
               help=_('Netmask to push into openvpn config')),
    cfg.StrOpt('vpn_key_suffix',
               default='-vpn',
               help='Suffix to add to project name for vpn key and secgroups'),
    ]

CONF = nova.conf.CONF
CONF.register_opts(cloudpipe_opts)
CONF.import_opt('keys_path', 'nova.crypto')

LOG = logging.getLogger(__name__)


def is_vpn_image(image_id):
    return image_id == CONF.vpn_image_id


def _load_boot_script():
    with open(CONF.boot_script_template, "r") as shellfile:
        s = string.Template(shellfile.read())
    return s.substitute(dmz_net=CONF.dmz_net,
                        dmz_mask=CONF.dmz_mask,
                        num_vpn=CONF.cnt_vpn_clients)


class CloudPipe(object):
    def __init__(self, skip_policy_check=False):
        self.compute_api = compute.API(skip_policy_check=skip_policy_check)

    def get_encoded_zip(self, project_id):
        # Make a payload.zip
        with utils.tempdir() as tmpdir:
            filename = "payload.zip"
            zippath = os.path.join(tmpdir, filename)
            z = zipfile.ZipFile(zippath, "w", zipfile.ZIP_DEFLATED)
            boot_script = _load_boot_script()
            # genvpn, sign csr
            crypto.generate_vpn_files(project_id)
            z.writestr('autorun.sh', boot_script)
            crl = os.path.join(crypto.ca_folder(project_id), 'crl.pem')
            z.write(crl, 'crl.pem')
            server_key = os.path.join(crypto.ca_folder(project_id),
                                      'server.key')
            z.write(server_key, 'server.key')
            ca_crt = os.path.join(crypto.ca_path(project_id))
            z.write(ca_crt, 'ca.crt')
            server_crt = os.path.join(crypto.ca_folder(project_id),
                                      'server.crt')
            z.write(server_crt, 'server.crt')
            z.close()
            with open(zippath, "r") as zippy:
                # NOTE(vish): run instances expects encoded userdata,
                # it is decoded in the get_metadata_call.
                # autorun.sh also decodes the zip file,
                # hence the double encoding.
                encoded = zippy.read().encode("base64").encode("base64")

        return encoded

    def launch_vpn_instance(self, context):
        LOG.debug("Launching VPN for %s", context.project_id)
        key_name = self.setup_key_pair(context)
        group_name = self.setup_security_group(context)
        flavor = flavors.get_flavor_by_name(CONF.vpn_flavor)
        instance_name = '%s%s' % (context.project_id, CONF.vpn_key_suffix)
        user_data = self.get_encoded_zip(context.project_id)
        return self.compute_api.create(context,
                                       flavor,
                                       CONF.vpn_image_id,
                                       display_name=instance_name,
                                       user_data=user_data,
                                       key_name=key_name,
                                       security_group=[group_name])

    def setup_security_group(self, context):
        group_name = '%s%s' % (context.project_id, CONF.vpn_key_suffix)
        group = {'user_id': context.user_id,
                 'project_id': context.project_id,
                 'name': group_name,
                 'description': 'Group for vpn'}
        try:
            group_ref = db.security_group_create(context, group)
        except exception.SecurityGroupExists:
            return group_name
        rule = {'parent_group_id': group_ref['id'],
                'cidr': '0.0.0.0/0',
                'protocol': 'udp',
                'from_port': 1194,
                'to_port': 1194}
        db.security_group_rule_create(context, rule)
        rule = {'parent_group_id': group_ref['id'],
                'cidr': '0.0.0.0/0',
                'protocol': 'icmp',
                'from_port': -1,
                'to_port': -1}
        db.security_group_rule_create(context, rule)
        # NOTE(vish): No need to trigger the group since the instance
        #             has not been run yet.
        return group_name

    def setup_key_pair(self, context):
        key_name = '%s%s' % (context.project_id, CONF.vpn_key_suffix)
        try:
            keypair_api = compute.api.KeypairAPI()
            result, private_key = keypair_api.create_key_pair(context,
                                                              context.user_id,
                                                              key_name)
            key_dir = os.path.join(CONF.keys_path, context.user_id)
            fileutils.ensure_tree(key_dir)
            key_path = os.path.join(key_dir, '%s.pem' % key_name)
            with open(key_path, 'w') as f:
                f.write(private_key)
        except (exception.KeyPairExists, os.error, IOError):
            pass
        return key_name
