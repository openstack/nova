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
"""Fakes relating to the `requests` module."""

import requests


class FakeResponse(requests.Response):
    def __init__(self, status_code, content=None, headers=None):
        """A requests.Response that can be used as a mock return_value.

        A key feature is that the instance will evaluate to True or False like
        a real Response, based on the status_code.

        Properties like ok, status_code, text, and content, and methods like
        json(), work as expected based on the inputs.

        :param status_code: Integer HTTP response code (200, 404, etc.)
        :param content: String supplying the payload content of the response.
                        Using a json-encoded string will make the json() method
                        behave as expected.
        :param headers: Dict of HTTP header values to set.
        """
        super(FakeResponse, self).__init__()
        self.status_code = status_code
        if content:
            self._content = content.encode('utf-8')
            self.encoding = 'utf-8'
        if headers:
            self.headers = headers
