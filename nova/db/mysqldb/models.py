# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Rackspace Hosting
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

"""
MySQLdb models
"""
_CUR_SCHEMA = {}


class _BaseModel(object):
    pass


class _BaseInstance(_BaseModel):
    __table__ = 'instances'

    # Joins
    info_cache = None
    metadata = None
    system_metadata = None
    instance_type = None

    _possible_joins = ['info_cache', 'metadata', 'system_metadata',
                       'instance_type']
    _default_joins = _possible_joins


def set_schema(schema):
    global _CUR_SCHEMA
    _CUR_SCHEMA = schema


def get_schema():
    return _CUR_SCHEMA
