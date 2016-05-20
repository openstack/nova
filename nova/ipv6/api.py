# Copyright (c) 2011 OpenStack Foundation
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

from stevedore import driver

import nova.conf

CONF = nova.conf.CONF
IMPL = None


def reset_backend():
    global IMPL
    IMPL = driver.DriverManager("nova.ipv6_backend",
                                CONF.ipv6_backend).driver


def to_global(prefix, mac, project_id):
    return IMPL.to_global(prefix, mac, project_id)


def to_mac(ipv6_address):
    return IMPL.to_mac(ipv6_address)


reset_backend()
