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

"""
:mod:`nova.endpoint` -- Main NOVA Api endpoints
=====================================================

.. automodule:: nova.endpoint
   :platform: Unix
   :synopsis: REST APIs for all nova functions
.. moduleauthor:: Jesse Andrews <jesse@ansolabs.com>
.. moduleauthor:: Devin Carlen <devin.carlen@gmail.com>
.. moduleauthor:: Vishvananda Ishaya <vishvananda@yahoo.com>
.. moduleauthor:: Joshua McKenty <joshua@cognition.ca>
.. moduleauthor:: Manish Singh <yosh@gimp.org>
.. moduleauthor:: Andy Smith <andy@anarkystic.com>
"""

from nova import wsgi
import routes
from nova.endpoint import rackspace
from nova.endpoint import aws

class APIVersionRouter(wsgi.Router):
    """Routes top-level requests to the appropriate API."""

    def __init__(self):
        mapper = routes.Mapper()
        rsapi = rackspace.API()
        mapper.connect(None, "/v1.0/{path_info:.*}", controller=rsapi)
        mapper.connect(None, "/ec2/{path_info:.*}", controller=aws.API())
        super(APIVersionRouter, self).__init__(mapper)
