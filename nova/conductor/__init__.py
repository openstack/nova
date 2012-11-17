#    Copyright 2012 IBM Corp.
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

from nova.conductor import api as conductor_api
import nova.openstack.common.cfg
import nova.openstack.common.importutils


def API(*args, **kwargs):
    if nova.openstack.common.cfg.CONF.conductor.use_local:
        api = conductor_api.LocalAPI
    else:
        api = conductor_api.API
    return api(*args, **kwargs)
