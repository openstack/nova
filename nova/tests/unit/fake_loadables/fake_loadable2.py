# Copyright 2012 OpenStack Foundation  # All Rights Reserved.
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
Fake Loadable subclasses module #2
"""

from nova.tests.unit import fake_loadables


class FakeLoadableSubClass5(fake_loadables.FakeLoadable):
    pass


class FakeLoadableSubClass6(fake_loadables.FakeLoadable):
    pass


class _FakeLoadableSubClass7(fake_loadables.FakeLoadable):
    """Classes beginning with '_' will be ignored."""
    pass


class FakeLoadableSubClass8(BaseException):
    """Not a correct subclass."""


def return_valid_class():
    return [FakeLoadableSubClass6]
