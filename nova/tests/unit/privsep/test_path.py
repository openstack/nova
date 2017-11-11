# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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

import os
import six
import tempfile

import nova.privsep.path
from nova import test


class LastBytesTestCase(test.NoDBTestCase):
    """Test the last_bytes() utility method."""

    def setUp(self):
        super(LastBytesTestCase, self).setUp()
        self.f = six.BytesIO(b'1234567890')

    def test_truncated(self):
        self.f.seek(0, os.SEEK_SET)
        out, remaining = nova.privsep.path._last_bytes_inner(self.f, 5)
        self.assertEqual(out, b'67890')
        self.assertGreater(remaining, 0)

    def test_read_all(self):
        self.f.seek(0, os.SEEK_SET)
        out, remaining = nova.privsep.path._last_bytes_inner(self.f, 1000)
        self.assertEqual(out, b'1234567890')
        self.assertFalse(remaining > 0)

    def test_seek_too_far_real_file(self):
        # StringIO doesn't raise IOError if you see past the start of the file.
        with tempfile.TemporaryFile() as flo:
            content = b'1234567890'
            flo.write(content)
            self.assertEqual(
                (content, 0),
                nova.privsep.path._last_bytes_inner(flo, 1000))
