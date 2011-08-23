# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from lxml import etree

from nova import utils


XMLNS_V10 = 'http://docs.rackspacecloud.com/servers/api/v1.0'
XMLNS_V11 = 'http://docs.openstack.org/compute/api/v1.1'
XMLNS_ATOM = 'http://www.w3.org/2005/Atom'


def validate_schema(xml, schema_name):
    if type(xml) is str:
        xml = etree.fromstring(xml)
    schema_path = os.path.join(utils.novadir(),
        'nova/api/openstack/schemas/v1.1/%s.rng' % schema_name)
    schema_doc = etree.parse(schema_path)
    relaxng = etree.RelaxNG(schema_doc)
    relaxng.assertValid(xml)
