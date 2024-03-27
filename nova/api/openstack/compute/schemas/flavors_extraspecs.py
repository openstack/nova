# Copyright 2014 NEC Corporation.  All rights reserved.
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

import copy

from nova.api.validation import parameter_types

_metadata_key = '^[a-zA-Z0-9-_:. ]{1,255}$'
# NOTE(oomichi): The metadata of flavor_extraspecs should accept numbers
# as its values.
_metadata = copy.deepcopy(parameter_types.metadata)
_metadata['patternProperties'][_metadata_key]['type'] = [
    'string', 'number'
]

create = {
    'type': 'object',
    'properties': {
        'extra_specs': _metadata
    },
    'required': ['extra_specs'],
    'additionalProperties': False,
}

update = copy.deepcopy(_metadata)
update.update({
     'minProperties': 1,
     'maxProperties': 1
})

# TODO(stephenfin): Remove additionalProperties in a future API version
index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_response = {
    'type': 'object',
    'properties': {
        # NOTE(stephenfin): While we accept numbers as values, we always return
        # strings
        'extra_specs': parameter_types.metadata,
    },
    'required': ['extra_specs'],
    'additionalProperties': False,
}

# NOTE(stephenfin): We return the request back to the user unmodified, meaning
# if the user provided a number key then they'll get a number key back, even
# though later requests will return a string
create_response = copy.deepcopy(create)

# NOTE(stephenfin): As above
update_response = copy.deepcopy(update)

# NOTE(stephenfin): Since we are retrieving here, we always return string keys
# (like index)
show_response = copy.deepcopy(parameter_types.metadata)

delete_response = {
    'type': 'null',
}
