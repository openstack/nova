# Copyright 2011 Justin Santa Barbara
# Copyright 2012 OpenStack Foundation
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

"""Implementation of a fake image service."""

from oslo_log import log as logging

import nova.conf
from nova import objects

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def fake_image_obj(default_image_meta=None, default_image_props=None,
                   variable_image_props=None):
    """Helper for constructing a test ImageMeta object with attributes and
    properties coming from a combination of (probably hard-coded)
    values within a test, and (optionally) variable values from the
    test's caller, if the test is actually a helper written to be
    reusable and run multiple times with different parameters from
    different "wrapper" tests.
    """
    image_meta_props = default_image_props or {}
    if variable_image_props:
        image_meta_props.update(variable_image_props)

    test_image_meta = default_image_meta or {"disk_format": "raw"}
    if 'name' not in test_image_meta:
        # NOTE(aspiers): the name is specified here in case it's needed
        # by the logging in nova.virt.hardware.get_mem_encryption_constraint()
        test_image_meta['name'] = 'fake_image'
    test_image_meta.update({
        'properties': image_meta_props,
    })

    return objects.ImageMeta.from_dict(test_image_meta)
