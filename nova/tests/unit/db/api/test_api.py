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

from unittest import mock

from nova.db.api import api as db_api
from nova import test


class SqlAlchemyDbApiNoDbTestCase(test.NoDBTestCase):

    @mock.patch.object(db_api, 'context_manager')
    def test_get_engine(self, mock_ctxt_mgr):
        db_api.get_engine()
        mock_ctxt_mgr.writer.get_engine.assert_called_once_with()
