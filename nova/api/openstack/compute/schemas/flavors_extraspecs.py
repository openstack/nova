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

# NOTE(oomichi): The metadata of flavor_extraspecs should accept numbers
# as its values.
metadata = copy.deepcopy(parameter_types.metadata)
metadata['patternProperties']['^[a-zA-Z0-9-_:. ]{1,255}$']['type'] = \
    ['string', 'number']
create = {
    'type': 'object',
    'properties': {
        'extra_specs': metadata
    },
    'required': ['extra_specs'],
    'additionalProperties': False,
}


update = copy.deepcopy(metadata)
update.update({
     'minProperties': 1,
     'maxProperties': 1
})
