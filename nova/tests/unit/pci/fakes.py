# Copyright (c) 2014 OpenStack Foundation
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

import functools

import mock

from nova.pci import whitelist


def fake_pci_whitelist():
    devspec = mock.Mock()
    devspec.get_tags.return_value = None
    patcher = mock.patch.object(whitelist.Whitelist, 'get_devspec',
                     return_value=devspec)
    patcher.start()
    return patcher


def patch_pci_whitelist(f):
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        patcher = fake_pci_whitelist()
        f(self, *args, **kwargs)
        patcher.stop()
    return wrapper
