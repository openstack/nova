# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

import uuid

from nova.tests.functional.v3 import api_sample_base
from nova.tests.unit.image import fake


class SchedulerHintsJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-scheduler-hints"

    def test_scheduler_hints_post(self):
        # Get api sample of scheduler hint post request.
        subs = self._get_regexes()
        subs.update({'image_id': fake.get_valid_image_id(),
                     'image_near': str(uuid.uuid4())})
        response = self._do_post('servers', 'scheduler-hints-post-req',
                                 subs)
        self._verify_response('scheduler-hints-post-resp', subs, response, 202)
