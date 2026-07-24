# Copyright 2016 Red Hat
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import contextlib
import os
from unittest import mock

from oslo_service import opts as oslo_svc_opts

from nova.cmd import compute
from nova import config
from nova import context
from nova.db.main import api as db
from nova import exception
from nova import test


@contextlib.contextmanager
def restore_db():
    orig = db.DISABLE_DB_ACCESS
    try:
        yield
    finally:
        db.DISABLE_DB_ACCESS = orig


class ComputeMainTest(test.NoDBTestCase):
    @mock.patch('nova.conductor.api.API.wait_until_ready')
    @mock.patch('oslo_reports.guru_meditation_report')
    def _call_main(self, mod, gmr, cond):
        @mock.patch.object(mod, 'config')
        @mock.patch.object(mod, 'service')
        def run_main(serv, conf):
            mod.main()

        run_main()

    def test_compute_main_blocks_db(self):
        ctxt = context.get_admin_context()
        with restore_db():
            self._call_main(compute)
            self.assertRaises(exception.DBNotAllowed, db.instance_get, ctxt, 2)


@mock.patch.object(config, 'parse_args', new=lambda *args, **kwargs: None)
class TestComputeConfig(test.NoDBTestCase):
    """Tests for config dump behaviour at nova-compute startup."""

    def setUp(self):
        super().setUp()
        # The config dump is only done in native threading mode; in eventlet
        # mode oslo.service handles it via the service manager path.
        if os.environ.get(
                'OS_NOVA_DISABLE_EVENTLET_PATCHING', '').lower() not in (
                '1', 'true', 'yes'):
            self.skipTest(
                "nova-compute config dump at startup is only applicable "
                "in native threading mode")
        # Pre-register oslo.service options (including log_options) so that
        # self.flags() can set them before compute.main() is called.
        oslo_svc_opts.register_service_opts(compute.CONF)

    def _call_main(self):
        """Call compute.main() with all external dependencies mocked out."""
        with mock.patch.object(compute, 'config'), \
             mock.patch.object(compute, 'service'), \
             mock.patch('nova.conductor.api.API.wait_until_ready'), \
             mock.patch('oslo_reports.guru_meditation_report'):
            with restore_db():
                compute.main()

    def test_config_dumped_at_startup_when_log_options_enabled(self):
        """Config options are dumped at startup when log_options is True."""
        self.flags(log_options=True)
        with mock.patch.object(compute.CONF, 'log_opt_values') as mock_dump:
            self._call_main()
        mock_dump.assert_called_once()

    def test_config_not_dumped_at_startup_when_log_options_disabled(self):
        """Config options are not dumped at startup when log_options is False.
        """
        self.flags(log_options=False)
        with mock.patch.object(compute.CONF, 'log_opt_values') as mock_dump:
            self._call_main()
        mock_dump.assert_not_called()
