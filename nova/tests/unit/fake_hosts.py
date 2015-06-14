# Copyright (c) 2012 OpenStack Foundation
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
Provides some fake hosts to test host and service related functions
"""

from nova.tests.unit.objects import test_service


HOST_LIST = [
        {"host_name": "host_c1", "service": "compute", "zone": "nova"},
        {"host_name": "host_c2", "service": "compute", "zone": "nova"}]

OS_API_HOST_LIST = {"hosts": HOST_LIST}

HOST_LIST_NOVA_ZONE = [
        {"host_name": "host_c1", "service": "compute", "zone": "nova"},
        {"host_name": "host_c2", "service": "compute", "zone": "nova"}]

service_base = test_service.fake_service

SERVICES_LIST = [
        dict(service_base, host='host_c1', topic='compute',
             binary='nova-compute'),
        dict(service_base, host='host_c2', topic='compute',
             binary='nova-compute')]
