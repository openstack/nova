# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

import logging
import os
import tempfile
import base64
from zipfile import ZipFile, ZIP_DEFLATED

from nova import exception
from nova import flags
from nova.auth import users
from nova import utils
from nova.endpoint import api

FLAGS = flags.FLAGS

flags.DEFINE_string('boot_script_template',
                    utils.abspath('cloudpipe/bootscript.sh'),
                    'Template for script to run on cloudpipe instance boot')

class CloudPipe(object):
    def __init__(self, cloud_controller):
        self.controller = cloud_controller
        self.manager = users.UserManager.instance()

    def launch_vpn_instance(self, project_id):
        logging.debug( "Launching VPN for %s" % (project_id))
        project = self.manager.get_project(project_id)
        # Make a payload.zip
        tmpfolder = tempfile.mkdtemp()
        filename = "payload.zip"
        zippath = os.path.join(tmpfolder, filename)
        z = ZipFile(zippath, "w", ZIP_DEFLATED)

        z.write(FLAGS.boot_script_template,'autorun.sh')
        z.close()

        key_name = self.setup_keypair(project.project_manager_id, project_id)
        zippy = open(zippath, "r")
        context = api.APIRequestContext(handler=None, user=project.project_manager, project=project)

        reservation = self.controller.run_instances(context,
            # run instances expects encoded userdata, it is decoded in the get_metadata_call
            # autorun.sh also decodes the zip file, hence the double encoding
            user_data=zippy.read().encode("base64").encode("base64"),
            max_count=1,
            min_count=1,
            instance_type='m1.tiny',
            image_id=FLAGS.vpn_image_id,
            key_name=key_name,
            security_groups=["vpn-secgroup"])
        zippy.close()

    def setup_keypair(self, user_id, project_id):
        key_name = '%s%s' % (project_id, FLAGS.vpn_key_suffix)
        try:
            private_key, fingerprint = self.manager.generate_key_pair(user_id, key_name)
            try:
                key_dir = os.path.join(FLAGS.keys_path, user_id)
                if not os.path.exists(key_dir):
                    os.makedirs(key_dir)
                with open(os.path.join(key_dir, '%s.pem' % key_name),'w') as f:
                    f.write(private_key)
            except:
                pass
        except exception.Duplicate:
            pass
        return key_name

    # def setup_secgroups(self, username):
    #     conn = self.euca.connection_for(username)
    #     try:
    #         secgroup = conn.create_security_group("vpn-secgroup", "vpn-secgroup")
    #         secgroup.authorize(ip_protocol = "udp", from_port = "1194", to_port = "1194", cidr_ip = "0.0.0.0/0")
    #         secgroup.authorize(ip_protocol = "tcp", from_port = "80", to_port = "80", cidr_ip = "0.0.0.0/0")
    #         secgroup.authorize(ip_protocol = "tcp", from_port = "22", to_port = "22", cidr_ip = "0.0.0.0/0")
    #     except:
    #         pass
