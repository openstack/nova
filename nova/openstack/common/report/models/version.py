# Copyright 2013 Red Hat, Inc.
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

"""Provides OpenStack Version Info Model

This module defines a class representing the data
model for OpenStack package and version information
"""

from nova.openstack.common.report.models import with_default_views as mwdv
from nova.openstack.common.report.views.text import generic as generic_text_views


class PackageModel(mwdv.ModelWithDefaultViews):
    """A Package Information Model

    This model holds information about the current
    package.  It contains vendor, product, and version
    information.

    :param str vendor: the product vendor
    :param str product: the product name
    :param str version: the product version
    """

    def __init__(self, vendor, product, version):
        super(PackageModel, self).__init__(
            text_view=generic_text_views.KeyValueView()
        )

        self['vendor'] = vendor
        self['product'] = product
        self['version'] = version
