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


class FakeImage(object):
    def __init__(self, metadata):
        IMAGE_ATTRIBUTES = ['size', 'disk_format', 'owner',
                            'container_format', 'checksum', 'id',
                            'name', 'created_at', 'updated_at',
                            'deleted', 'deleted_at', 'status',
                            'min_disk', 'min_ram', 'is_public']
        raw = dict.fromkeys(IMAGE_ATTRIBUTES)
        raw.update(metadata)
        self.__dict__['raw'] = raw

    def __getattr__(self, key):
        try:
            return self.__dict__['raw'][key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        try:
            self.__dict__['raw'][key] = value
        except KeyError:
            raise AttributeError(key)
