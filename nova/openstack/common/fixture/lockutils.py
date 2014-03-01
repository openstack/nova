# Copyright 2011 OpenStack Foundation.
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

import fixtures

from nova.openstack.common import lockutils


class LockFixture(fixtures.Fixture):
    """External locking fixture.

    This fixture is basically an alternative to the synchronized decorator with
    the external flag so that tearDowns and addCleanups will be included in
    the lock context for locking between tests. The fixture is recommended to
    be the first line in a test method, like so::

        def test_method(self):
            self.useFixture(LockFixture)
                ...

    or the first line in setUp if all the test methods in the class are
    required to be serialized. Something like::

        class TestCase(testtools.testcase):
            def setUp(self):
                self.useFixture(LockFixture)
                super(TestCase, self).setUp()
                    ...

    This is because addCleanups are put on a LIFO queue that gets run after the
    test method exits. (either by completing or raising an exception)
    """
    def __init__(self, name, lock_file_prefix=None):
        self.mgr = lockutils.lock(name, lock_file_prefix, True)

    def setUp(self):
        super(LockFixture, self).setUp()
        self.addCleanup(self.mgr.__exit__, None, None, None)
        self.mgr.__enter__()
