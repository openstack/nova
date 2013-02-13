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
import sys

_CUR_SCHEMA = {}
_OUR_MODULE = sys.modules[__name__]
_MODEL_MAP = {}


class _BaseModel(object):
    pass


class _BaseInstance(_BaseModel):
    __model__ = 'Instance'
    __table__ = 'instances'

    # Joins
    info_cache = None
    metadata = None
    system_metadata = None
    instance_type = None

    _possible_joins = ['info_cache', 'metadata', 'system_metadata',
                       'instance_type']
    _default_joins = _possible_joins


def _table_to_base_model_mapping():
    mapping = {}
    for obj_name in dir(_OUR_MODULE):
        obj = getattr(_OUR_MODULE, obj_name)
        try:
            if issubclass(obj, _BaseModel) and obj_name != '_BaseModel':
                mapping[obj.__table__] = obj
        except TypeError:
            continue
    return mapping


class Models(object):
    """This will have attributes for every model.  Ie, 'Instance'.
    This gets setattr'd every time we update the schema, so it's an
    atomic swap.  This is here just so pylint, etc is happy.
    """
    pass


class SomeMixInClass(object):
    pass


def _create_models(schema, mixin_cls):
    tbl_to_base_model = _table_to_base_model_mapping()
    version = schema['version']
    models_obj = type('Models', (object, ), {})
    for table in schema['tables']:
        base_model = tbl_to_base_model.get(table)
        if not base_model:
            continue
        model_name = base_model.__model__
        vers_model_name = '%s_v%s' % (base_model.__model__, str(version))
        vers_model = type(vers_model_name, (base_model, ), {})
        model = type(model_name, (vers_model, mixin_cls),
                {'__repo_version__': version})
        setattr(models_obj, model_name, model)
    setattr(_OUR_MODULE, 'Models', models_obj)

def set_schema(schema):
    global _CUR_SCHEMA
    _create_models(schema, SomeMixInClass)
    _CUR_SCHEMA = schema


def get_schema():
    return _CUR_SCHEMA
