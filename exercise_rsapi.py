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

import cloudservers

class IdFake:
    def __init__(self, id):
        self.id = id

# to get your access key:
# from nova.auth import users
# users.UserManger.instance().get_users()[0].access
rscloud = cloudservers.CloudServers(
            'admin',
            '6cca875e-5ab3-4c60-9852-abf5c5c60cc6'
          )
rscloud.client.AUTH_URL = 'http://localhost:8773/v1.0'


rv = rscloud.servers.list()
print "SERVERS: %s" % rv

if len(rv) == 0:
    server = rscloud.servers.create(
               "test-server",
               IdFake("ami-tiny"),
               IdFake("m1.tiny")
             )
    print "LAUNCH: %s" % server
else:
    server = rv[0]
    print "Server to kill: %s" % server

raw_input("press enter key to kill the server")

server.delete()
