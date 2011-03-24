# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import boto
import commands
import httplib
import os
import paramiko
import sys
import time
import unittest
from boto.ec2.regioninfo import RegionInfo

from smoketests import flags

SUITE_NAMES = '[image, instance, volume]'
FLAGS = flags.FLAGS
flags.DEFINE_string('suite', None, 'Specific test suite to run ' + SUITE_NAMES)
flags.DEFINE_integer('ssh_tries', 3, 'Numer of times to try ssh')


class SmokeTestCase(unittest.TestCase):
    def connect_ssh(self, ip, key_name):
        key = paramiko.RSAKey.from_private_key_file('/tmp/%s.pem' % key_name)
        tries = 0
        while(True):
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
                client.connect(ip, username='root', pkey=key, timeout=5)
                return client
            except (paramiko.AuthenticationException, paramiko.SSHException):
                tries += 1
                if tries == FLAGS.ssh_tries:
                    raise

    def can_ping(self, ip, command="ping"):
        """Attempt to ping the specified IP, and give up after 1 second."""

        # NOTE(devcamcar): ping timeout flag is different in OSX.
        if sys.platform == 'darwin':
            timeout_flag = 't'
        else:
            timeout_flag = 'w'

        status, output = commands.getstatusoutput('%s -c1 -%s1 %s' %
                                                  (command, timeout_flag, ip))
        return status == 0

    def wait_for_running(self, instance, tries=60, wait=1):
        """Wait for instance to be running"""
        for x in xrange(tries):
            instance.update()
            if instance.state.startswith('running'):
                return True
            time.sleep(wait)
        else:
            return False

    def wait_for_ping(self, ip, command="ping", tries=120):
        """Wait for ip to be pingable"""
        for x in xrange(tries):
            if self.can_ping(ip, command):
                return True
        else:
            return False

    def wait_for_ssh(self, ip, key_name, tries=30, wait=5):
        """Wait for ip to be sshable"""
        for x in xrange(tries):
            try:
                conn = self.connect_ssh(ip, key_name)
                conn.close()
            except Exception, e:
                time.sleep(wait)
            else:
                return True
        else:
            return False

    def connection_for_env(self, **kwargs):
        """
        Returns a boto ec2 connection for the current environment.
        """
        access_key = os.getenv('EC2_ACCESS_KEY')
        secret_key = os.getenv('EC2_SECRET_KEY')
        clc_url = os.getenv('EC2_URL')

        if not access_key or not secret_key or not clc_url:
            raise Exception('Missing EC2 environment variables. Please source '
                            'the appropriate novarc file before running this '
                            'test.')

        parts = self.split_clc_url(clc_url)
        if FLAGS.use_ipv6:
            return boto_v6.connect_ec2(aws_access_key_id=access_key,
                                aws_secret_access_key=secret_key,
                                is_secure=parts['is_secure'],
                                region=RegionInfo(None,
                                                  'nova',
                                                  parts['ip']),
                                port=parts['port'],
                                path='/services/Cloud',
                                **kwargs)

        return boto.connect_ec2(aws_access_key_id=access_key,
                                aws_secret_access_key=secret_key,
                                is_secure=parts['is_secure'],
                                region=RegionInfo(None,
                                                  'nova',
                                                  parts['ip']),
                                port=parts['port'],
                                path='/services/Cloud',
                                **kwargs)

    def split_clc_url(self, clc_url):
        """
        Splits a cloud controller endpoint url.
        """
        parts = httplib.urlsplit(clc_url)
        is_secure = parts.scheme == 'https'
        ip, port = parts.netloc.split(':')
        return {'ip': ip, 'port': int(port), 'is_secure': is_secure}

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

    def bundle_image(self, image, tempdir='/tmp', kernel=False):
        cmd = 'euca-bundle-image -i %s -d %s' % (image, tempdir)
        if kernel:
            cmd += ' --kernel true'
        status, output = commands.getstatusoutput(cmd)
        if status != 0:
            print '%s -> \n %s' % (cmd, output)
            raise Exception(output)
        return True

    def upload_image(self, bucket_name, image, tempdir='/tmp'):
        cmd = 'euca-upload-bundle -b '
        cmd += '%s -m %s/%s.manifest.xml' % (bucket_name, tempdir, image)
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


TEST_DATA = {}
if FLAGS.use_ipv6:
    global boto_v6
    boto_v6 = __import__('boto_v6')


class UserSmokeTestCase(SmokeTestCase):
    def setUp(self):
        global TEST_DATA
        self.conn = self.connection_for_env()
        self.data = TEST_DATA
