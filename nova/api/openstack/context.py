# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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
APIRequestContext
"""

import random

class Project(object):
    def __init__(self, user_id):
        self.id = user_id
    
class APIRequestContext(object):
    """ This is an adapter class to get around all of the assumptions made in
    the FlatNetworking """
    def __init__(self, user_id):
        self.user_id = user_id
        self.project = Project(user_id)
