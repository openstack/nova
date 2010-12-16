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
import random
import sys
import unittest
from boto.ec2.regioninfo import RegionInfo

from smoketests import flags

FLAGS = flags.FLAGS


class SmokeTestCase(unittest.TestCase):
    def connect_ssh(self, ip, key_name):
        # TODO(devcamcar): set a more reasonable connection timeout time
        key = paramiko.RSAKey.from_private_key_file('/tmp/%s.pem' % key_name)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(ip, username='root', pkey=key)
        stdin, stdout, stderr = client.exec_command('uptime')
        print 'uptime: ', stdout.read()
        return client

    def can_ping(self, ip):
        """ Attempt to ping the specified IP, and give up after 1 second. """

        # NOTE(devcamcar): ping timeout flag is different in OSX.
        if sys.platform == 'darwin':
            timeout_flag = 't'
        else:
            timeout_flag = 'w'

        status, output = commands.getstatusoutput('ping -c1 -%s1 %s' %
                                                  (timeout_flag, ip))
        return status == 0

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

def run_tests(suites):
    argv = FLAGS(sys.argv)

    if not os.getenv('EC2_ACCESS_KEY'):
        print >> sys.stderr, 'Missing EC2 environment variables. Please ' \
                             'source the appropriate novarc file before ' \
                             'running this test.'
        return 1

    if FLAGS.suite:
        try:
            suite = suites[FLAGS.suite]
        except KeyError:
            print >> sys.stderr, 'Available test suites:', \
                                 ', '.join(suites.keys())
            return 1

        unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        for suite in suites.itervalues():
            unittest.TextTestRunner(verbosity=2).run(suite)

