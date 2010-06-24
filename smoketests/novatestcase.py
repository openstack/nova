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

import commands
import os
import random
import sys
import unittest

from nova.adminclient import NovaAdminClient
from nova.smoketests import flags

from nova import vendor
import paramiko

nova_admin = NovaAdminClient(access_key=flags.admin_access_key, secret_key=flags.admin_secret_key, clc_ip=host)

class NovaTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def connect_ssh(self, ip, key_name):
        # TODO(devcamcar): set a more reasonable connection timeout time
        key = paramiko.RSAKey.from_private_key_file('/tmp/%s.pem' % key_name)
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(ip, username='root', pkey=key)
        stdin, stdout, stderr = client.exec_command('uptime')
        print 'uptime: ', stdout.read()
        return client

    def can_ping(self, ip):
        return commands.getstatusoutput('ping -c 1 %s' % ip)[0] == 0

    @property
    def admin(self):
        return nova_admin.connection_for('admin')

    def connection_for(self, username):
        return nova_admin.connection_for(username)

    def create_user(self, username):
        return nova_admin.create_user(username)

    def get_user(self, username):
        return nova_admin.get_user(username)

    def delete_user(self, username):
        return nova_admin.delete_user(username)

    def get_signed_zip(self, username):
        return nova_admin.get_zip(username)

    def create_key_pair(self, conn, key_name):
        try:
            os.remove('/tmp/%s.pem' % key_name)
        except:
            pass
        key = conn.create_key_pair(key_name)
        key.save('/tmp/')
        return key

    def delete_key_pair(self, conn, key_name):
        conn.delete_key_pair(key_name)
        try:
            os.remove('/tmp/%s.pem' % key_name)
        except:
            pass

    def bundle_image(self, image, kernel=False):
        cmd = 'euca-bundle-image -i %s' % image
        if kernel:
            cmd += ' --kernel true'
        status, output = commands.getstatusoutput(cmd)
        if status != 0:
            print '%s -> \n %s' % (cmd, output)
            raise Exception(output)
        return True

    def upload_image(self, bucket_name, image):
        cmd = 'euca-upload-bundle -b %s -m /tmp/%s.manifest.xml' % (bucket_name, image)
        status, output = commands.getstatusoutput(cmd)
        if status != 0:
            print '%s -> \n %s' % (cmd, output)
            raise Exception(output)
        return True

    def delete_bundle_bucket(self, bucket_name):
        cmd = 'euca-delete-bundle --clear -b %s' % (bucket_name)
        status, output = commands.getstatusoutput(cmd)
        if status != 0:
            print '%s -> \n%s' % (cmd, output)
            raise Exception(output)
        return True

    def register_image(self, bucket_name, manifest):
        conn = nova_admin.connection_for('admin')
        return conn.register_image("%s/%s.manifest.xml" % (bucket_name, manifest))

    def setUp_test_image(self, image, kernel=False):
        self.bundle_image(image, kernel=kernel)
        bucket = "auto_test_%s" % int(random.random() * 1000000)
        self.upload_image(bucket, image)
        return self.register_image(bucket, image)

    def tearDown_test_image(self, conn, image_id):
        conn.deregister_image(image_id)
