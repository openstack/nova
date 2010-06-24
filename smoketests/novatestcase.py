# COPYRIGHT NASA

import os, unittest, sys
from commands import getstatusoutput
from paramiko import SSHClient, RSAKey, AutoAddPolicy
import random

BUCKET_NAME = 'smoketest'

try:
    # pulling from environment means euca-bundle and other shell commands
    # are runable without futzing with the environment and zip files
    access_key = os.environ['EC2_ACCESS_KEY']
    secret_key = os.environ['EC2_SECRET_KEY']
    endpoint = os.environ['EC2_URL']
    host = endpoint.split('/')[2].split(':')[0] # http://HOST:8773/services/Cloud
except:
    print 'you need to source admin rc before running smoketests'
    sys.exit(2)

from nova.adminclient import NovaAdminClient
admin = NovaAdminClient(access_key=access_key, secret_key=secret_key, clc_ip=host)

class NovaTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def connect_ssh(self, ip, key_name):
        # TODO: set a more reasonable connection timeout time
        key = RSAKey.from_private_key_file('/tmp/%s.pem' % key_name)
        client = SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(AutoAddPolicy())
        client.connect(ip, username='ubuntu', pkey=key)
        stdin, stdout, stderr = client.exec_command('uptime')
        print 'uptime: ', stdout.read()
        return client

    def can_ping(self, ip):
        return getstatusoutput('ping -c 1 %s' % ip)[0] == 0

    @property
    def admin(self):
        return admin.connection_for('admin')

    def connection_for(self, username):
        return admin.connection_for(username)

    def create_user(self, username):
        return admin.create_user(username)

    def get_user(self, username):
        return admin.get_user(username)

    def delete_user(self, username):
        return admin.delete_user(username)

    def get_signed_zip(self, username):
        return admin.get_zip(username)

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
        status, output = getstatusoutput(cmd)
        if status != 0:
            print '%s -> \n %s' % (cmd, output)
            raise Exception(output)
        return True

    def upload_image(self, bucket_name, image):
        cmd = 'euca-upload-bundle -b %s -m /tmp/%s.manifest.xml' % (bucket_name, image)
        status, output = getstatusoutput(cmd)
        if status != 0:
            print '%s -> \n %s' % (cmd, output)
            raise Exception(output)
        return True

    def delete_bundle_bucket(self, bucket_name):
        cmd = 'euca-delete-bundle --clear -b %s' % (bucket_name)
        status, output = getstatusoutput(cmd)
        if status != 0:
            print '%s -> \n%s' % (cmd, output)
            raise Exception(output)
        return True

    def register_image(self, bucket_name, manifest):
        conn = admin.connection_for('admin')
        return conn.register_image("%s/%s.manifest.xml" % (bucket_name, manifest))

    def setUp_test_image(self, image, kernel=False):
        self.bundle_image(image, kernel=kernel)
        bucket = "auto_test_%s" % int(random.random() * 1000000)
        self.upload_image(bucket, image)
        return self.register_image(bucket, image)

    def tearDown_test_image(self, conn, image_id):
        conn.deregister_image(image_id)
