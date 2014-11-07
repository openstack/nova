# Copyright (C) 2013 eNovance SAS <licensing@enovance.com>
#
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

from nova import test
from nova.virt.libvirt import designer


class DesignerTestCase(test.NoDBTestCase):
    def test_set_vif_bandwidth_config_no_extra_specs(self):
        # Test whether test_set_vif_bandwidth_config_no_extra_specs fails when
        # its second parameter has no 'extra_specs' field.

        try:
            # The conf will never be user be used, so we can use 'None'.
            # An empty dictionary is fine: all that matters it that there is no
            # 'extra_specs' field.
            designer.set_vif_bandwidth_config(None, {})
        except KeyError as e:
            self.fail('KeyError: %s' % e)
