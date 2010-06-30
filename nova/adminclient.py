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
Nova User API client library.
"""

import boto
from boto.ec2.regioninfo import RegionInfo
import base64

class UserInfo(object):
    """ Information about a Nova user
    fields include:
        username
        accesskey
        secretkey

    and an optional field containing a zip with X509 cert & rc
        file
    """

    def __init__(self, connection=None, username=None, endpoint=None):
        self.connection = connection
        self.username = username
        self.endpoint = endpoint

    def __repr__(self):
        return 'UserInfo:%s' % self.username

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'username':
            self.username = str(value)
        elif name == 'file':
            self.file = base64.b64decode(str(value))
        elif name == 'accesskey':
            self.accesskey = str(value)
        elif name == 'secretkey':
            self.secretkey = str(value)


class NovaAdminClient(object):
    def __init__(self, clc_ip='127.0.0.1', region='nova', access_key='admin',
                 secret_key='admin', **kwargs):
        self.clc_ip = clc_ip
        self.region = region
        self.access = access_key
        self.secret = secret_key
        self.apiconn = boto.connect_ec2(aws_access_key_id=access_key,
                                        aws_secret_access_key=secret_key,
                                        is_secure=False,
                                        region=RegionInfo(None, region, clc_ip),
                                        port=8773,
                                        path='/services/Admin',
                                        **kwargs)
        self.apiconn.APIVersion = 'nova'

    def connection_for(self, username, **kwargs):
        """
        Returns a boto ec2 connection for the given username.
        """
        user = self.get_user(username)
        return boto.connect_ec2(
            aws_access_key_id=user.accesskey,
            aws_secret_access_key=user.secretkey,
            is_secure=False,
            region=RegionInfo(None, self.region, self.clc_ip),
            port=8773,
            path='/services/Cloud',
            **kwargs
        )

    def get_users(self):
        """ grabs the list of all users """
        return self.apiconn.get_list('DescribeUsers', {}, (['item', UserInfo]))

    def get_user(self, name):
        """ grab a single user by name """
        user = self.apiconn.get_object('DescribeUser', {'Name': name}, UserInfo)

        if user.username != None:
            return user

    def has_user(self, username):
        """ determine if user exists """
        return self.get_user(username) != None

    def create_user(self, username):
        """ creates a new user, returning the userinfo object with access/secret """
        return self.apiconn.get_object('RegisterUser', {'Name': username}, UserInfo)

    def delete_user(self, username):
        """ deletes a user """
        return self.apiconn.get_object('DeregisterUser', {'Name': username}, UserInfo)

    def get_zip(self, username):
        """ returns the content of a zip file containing novarc and access credentials. """
        return self.apiconn.get_object('GenerateX509ForUser', {'Name': username}, UserInfo).file

