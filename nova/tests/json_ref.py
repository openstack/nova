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

import os

from oslo_serialization import jsonutils


def _resolve_ref(ref, base_path):
    file_path, _, json_path = ref.partition('#')
    if json_path:
        raise NotImplementedError('JSON refs with JSON path after the "#" is '
                                  'not yet supported')

    path = os.path.join(base_path, file_path)
    # binary mode is needed due to bug/1515231
    with open(path, 'r+b') as f:
        ref_value = jsonutils.load(f)
        base_path = os.path.dirname(path)
        res = resolve_refs(ref_value, base_path)
        return res


def resolve_refs(obj_with_refs, base_path):
    if isinstance(obj_with_refs, list):
        for i, item in enumerate(obj_with_refs):
            obj_with_refs[i] = resolve_refs(item, base_path)
    elif isinstance(obj_with_refs, dict):
        if '$ref' in obj_with_refs.keys():
            ref = obj_with_refs.pop('$ref')
            resolved_ref = _resolve_ref(ref, base_path)
            # the rest of the ref dict contains overrides for the ref. Apply
            # those overrides recursively here.
            _update_dict_recursively(resolved_ref, obj_with_refs)
            return resolved_ref
        else:
            for key, value in obj_with_refs.items():
                obj_with_refs[key] = resolve_refs(value, base_path)
    else:
        # scalar, nothing to do
        pass

    return obj_with_refs


def _update_dict_recursively(d, update):
    """Update dict d recursively with data from dict update"""
    for k, v in update.items():
        if k in d and isinstance(d[k], dict) and isinstance(v, dict):
            _update_dict_recursively(d[k], v)
        else:
            d[k] = v
