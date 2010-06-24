# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
CloudPipe - Build a user-data payload zip file, and launch
an instance with it.

"""

import logging
import os
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

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

    def launch_vpn_instance(self, username):
        logging.debug( "Launching VPN for %s" % (username))
        user = self.manager.get_user(username)
        # Make a payload.zip
        tmpfolder = tempfile.mkdtemp()
        filename = "payload.zip"
        zippath = os.path.join(tmpfolder, filename)
        z = ZipFile(zippath, "w", ZIP_DEFLATED)

        z.write(FLAGS.boot_script_template,'autorun.sh')
        z.close()

        self.setup_keypair(username)
        zippy = open(zippath, "r")
        context = api.APIRequestContext(handler=None, user=user)

        reservation = self.controller.run_instances(context,
            user_data=zippy.read().encode("base64"),
            max_count=1,
            min_count=1,
            image_id=FLAGS.vpn_image_id,
            key_name="vpn-key",
            security_groups=["vpn-secgroup"])
        zippy.close()

    def setup_keypair(self, username):
        try:
            private_key, fingerprint = self.manager.generate_key_pair(username, "vpn-key")
            os.mkdir("%s/%s" % (FLAGS.keys_path, username))
            private_key.save(os.path.abspath("%s/%s" % (FLAGS.keys_path, username)))
        except:
            pass

    # def setup_secgroups(self, username):
    #     conn = self.euca.connection_for(username)
    #     try:
    #         secgroup = conn.create_security_group("vpn-secgroup", "vpn-secgroup")
    #         secgroup.authorize(ip_protocol = "udp", from_port = "1194", to_port = "1194", cidr_ip = "0.0.0.0/0")
    #         secgroup.authorize(ip_protocol = "tcp", from_port = "80", to_port = "80", cidr_ip = "0.0.0.0/0")
    #         secgroup.authorize(ip_protocol = "tcp", from_port = "22", to_port = "22", cidr_ip = "0.0.0.0/0")
    #     except:
    #         pass
