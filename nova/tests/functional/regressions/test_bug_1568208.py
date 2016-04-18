# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


from oslo_reports import guru_meditation_report as gmr

from nova import test
from nova import version


class TestServerGet(test.TestCase):

    def test_guru_meditation_report_generation(self):
        """Regression test for bug #1568208.

        This test ensures a text guru meditation report can be generated
        successfully and generation does not fail e.g. due to incorrectly
        registered config options.

        """

        # NOTE(rpodolyaka): we are only interested in success of run() call
        # here, it's up to oslo_reports tests to check the generated report
        generator = gmr.TextGuruMeditation(version)
        generator.run()
