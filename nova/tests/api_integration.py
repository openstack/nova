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

import unittest

import boto
from boto.ec2.regioninfo import RegionInfo

ACCESS_KEY = 'fake'
SECRET_KEY = 'fake'
CLC_IP = '127.0.0.1'
CLC_PORT = 8773
REGION = 'test'

def get_connection():
    return boto.connect_ec2 (
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        is_secure=False,
        region=RegionInfo(None, REGION, CLC_IP),
        port=CLC_PORT,
        path='/services/Cloud',
        debug=99
    )

class APIIntegrationTests(unittest.TestCase):
    def test_001_get_all_images(self):
        conn = get_connection()
        res = conn.get_all_images()


if __name__ == '__main__':
    unittest.main()

#print conn.get_all_key_pairs()
#print conn.create_key_pair
#print conn.create_security_group('name', 'description')

