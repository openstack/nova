# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
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

import StringIO

import glance.client


def stubout_glance_client(stubs, cls):
    """Stubs out glance.client.Client"""
    stubs.Set(glance.client, 'Client',
              lambda *args, **kwargs: cls(*args, **kwargs))


class FakeGlance(object):
    def __init__(self, host, port=None, use_ssl=False):
        pass

    def get_image_meta(self, image_id):
        return {'size': 0, 'properties': {}}

    def get_image(self, image_id):
        meta = self.get_image_meta(image_id)
        image_file = StringIO.StringIO('')
        return meta, image_file
