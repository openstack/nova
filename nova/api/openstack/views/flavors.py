# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

from nova.api.openstack import common


class ViewBuilder(object):
    def __init__(self):
        pass

    def build(self, flavor_obj):
        raise NotImplementedError()


class ViewBuilderV11(ViewBuilder):
    def __init__(self, base_url):
        self.base_url = base_url

    def generate_href(self, flavor_id):
        return "%s/flavors/%s" % (self.base_url, flavor_id)
