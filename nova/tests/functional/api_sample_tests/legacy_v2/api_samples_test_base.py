# Copyright 2015 Intel Corporation.
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

import os.path
from oslo_utils import importutils

from nova.tests.functional import api_samples_test_base


class ApiSampleTestBase(api_samples_test_base.ApiSampleTestBase):

    @classmethod
    def _get_sample_path(cls, name, dirname, suffix='', api_version=None):
        parts = [dirname]
        if cls.all_extensions:
            parts.append('all_extensions')
        # Note(gmann): if _use_common_server_api_samples is set to True
        # then common server sample files present in 'servers' directory
        # will be used.
        elif cls._use_common_server_api_samples:
            parts.append('servers')
        elif cls.sample_dir:
            parts.append(cls.sample_dir)
        elif cls.extension_name:
            alias = importutils.import_class(cls.extension_name).alias
            parts.append(alias)
        parts.append(name + "." + cls.ctype + suffix)
        return os.path.join(*parts)

    @classmethod
    def _get_sample(cls, name, api_version=None):
        dirname = os.path.dirname(os.path.abspath(__file__))
        dirname = os.path.normpath(
            os.path.join(dirname, "../../../../../doc/api_samples/legacy_v2"))
        return cls._get_sample_path(name, dirname, api_version=api_version)

    @classmethod
    def _get_template(cls, name, api_version=None):
        dirname = os.path.dirname(os.path.abspath(__file__))
        return cls._get_sample_path(name, dirname, suffix='.tpl',
                                    api_version=api_version)
