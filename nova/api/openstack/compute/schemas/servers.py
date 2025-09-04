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
from nova.api.validation.parameter_types import multi_params
from nova.objects import instance

_legacy_block_device_mapping = {
    'type': 'object',
    'properties': {
        'virtual_name': {
            'type': 'string', 'maxLength': 255,
        },
        'volume_id': parameter_types.volume_id,
        'snapshot_id': parameter_types.image_id,
        'volume_size': parameter_types.volume_size,
        # Do not allow empty device names or spaces in name (defined in
        # nova/block_device.py:validate_device_name())
        'device_name': {
            'type': 'string', 'minLength': 1, 'maxLength': 255,
            'pattern': '^[a-zA-Z0-9._/-]*$',
        },
        # Defined as boolean in nova/block_device.py:from_api()
        'delete_on_termination': parameter_types.boolean,
        'no_device': {},
        # Defined as mediumtext in column "connection_info" in table
        # "block_device_mapping"
        'connection_info': {
            'type': 'string', 'maxLength': 16777215
        },
    },
    'additionalProperties': False
}

_block_device_mapping_v2_new_item = {
    # defined in nova/block_device.py:from_api()
    # NOTE: Client can specify the Id with the combination of
    # source_type and uuid, or a single attribute like volume_id/
    # image_id/snapshot_id.
    'source_type': {
        'type': 'string',
        'enum': ['volume', 'image', 'snapshot', 'blank'],
    },
    'uuid': {
        'type': 'string', 'minLength': 1, 'maxLength': 255,
        'pattern': '^[a-zA-Z0-9._-]*$',
    },
    'image_id': parameter_types.image_id,
    'destination_type': {
        'type': 'string',
        'enum': ['local', 'volume'],
    },
    # Defined as varchar(255) in column "guest_format" in table
    # "block_device_mapping"
    'guest_format': {
        'type': 'string', 'maxLength': 255,
    },
    # Defined as varchar(255) in column "device_type" in table
    # "block_device_mapping"
    'device_type': {
        'type': 'string', 'maxLength': 255,
    },
    # Defined as varchar(255) in column "disk_bus" in table
    # "block_device_mapping"
    'disk_bus': {
        'type': 'string', 'maxLength': 255,
    },
    # Defined as integer in nova/block_device.py:from_api()
    # NOTE(mriedem): boot_index=None is also accepted for backward
    # compatibility with the legacy v2 API.
    'boot_index': {
        'type': ['integer', 'string', 'null'],
        'pattern': '^-?[0-9]+$',
    },
}

_block_device_mapping_v2 = copy.deepcopy(_legacy_block_device_mapping)
_block_device_mapping_v2['properties'].update(
    _block_device_mapping_v2_new_item
)

_hints = {
    'type': 'object',
    'properties': {
        'group': {
            'type': 'string',
            'format': 'uuid'
        },
        'different_host': {
            # NOTE: The value of 'different_host' is the set of server
            # uuids where a new server is scheduled on a different host.
            # A user can specify one server as string parameter and should
            # specify multiple servers as array parameter instead.
            'oneOf': [
                {
                    'type': 'string',
                    'format': 'uuid'
                },
                {
                    'type': 'array',
                    'items': parameter_types.server_id
                }
            ]
        },
        'same_host': {
            # NOTE: The value of 'same_host' is the set of server
            # uuids where a new server is scheduled on the same host.
            'type': ['string', 'array'],
            'items': parameter_types.server_id
        },
        'query': {
            # NOTE: The value of 'query' is converted to dict data with
            # jsonutils.loads() and used for filtering hosts.
            'type': ['string', 'object'],
        },
        # NOTE: The value of 'target_cell' is the cell name what cell
        # a new server is scheduled on.
        'target_cell': parameter_types.name,
        'different_cell': {
            'type': ['string', 'array'],
            'items': {
                'type': 'string'
            }
        },
        'build_near_host_ip': parameter_types.ip_address,
        'cidr': {
            'type': 'string',
            'pattern': '^/[0-9a-f.:]+$'
        },
    },
    # NOTE: As this Mail:
    # http://lists.openstack.org/pipermail/openstack-dev/2015-June/067996.html
    # pointed out the limit the scheduler-hints in the API is problematic. So
    # relax it.
    'additionalProperties': True
}

create = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                # NOTE(gmann): In case of boot from volume, imageRef was
                # allowed as the empty string also So keeping the same
                # behavior and allow empty string in case of boot from
                # volume only. Python code make sure empty string is
                # not allowed for other cases.
                'imageRef': parameter_types.image_id_or_empty_string,
                'flavorRef': parameter_types.flavor_ref,
                'adminPass': parameter_types.admin_password,
                'metadata': parameter_types.metadata,
                'networks': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'fixed_ip': parameter_types.ip_address,
                            'port': {
                                'oneOf': [{'type': 'string', 'format': 'uuid'},
                                          {'type': 'null'}]
                            },
                            'uuid': {'type': 'string'},
                        },
                        'additionalProperties': False,
                    }
                },
                'OS-DCF:diskConfig': parameter_types.disk_config,
                'accessIPv4': parameter_types.accessIPv4,
                'accessIPv6': parameter_types.accessIPv6,
                'personality': parameter_types.personality,
                'availability_zone': parameter_types.name,
                'block_device_mapping': {
                    'type': 'array',
                    'items': _legacy_block_device_mapping
                },
                'block_device_mapping_v2': {
                    'type': 'array',
                    'items': _block_device_mapping_v2
                },
                'config_drive': parameter_types.boolean,
                'key_name': parameter_types.name,
                'min_count': parameter_types.positive_integer,
                'max_count': parameter_types.positive_integer,
                'return_reservation_id': parameter_types.boolean,
                'security_groups': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            # NOTE(oomichi): allocate_for_instance() of
                            # network/neutron.py gets security_group names
                            # or UUIDs from this parameter.
                            # parameter_types.name allows both format.
                            'name': parameter_types.name,
                        },
                        'additionalProperties': False,
                    }
                },
                'user_data': {
                    'type': 'string',
                    'format': 'base64',
                    'maxLength': 65535
                }
            },
            'required': ['name', 'flavorRef'],
            'additionalProperties': False,
        },
        'os:scheduler_hints': _hints,
        'OS-SCH-HNT:scheduler_hints': _hints,
    },
    'required': ['server'],
    'additionalProperties': False,
}

create_v20 = copy.deepcopy(create)
create_v20['properties']['server'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces
create_v20['properties']['server']['properties'][
    'availability_zone'] = parameter_types.name_with_leading_trailing_spaces
create_v20['properties']['server']['properties'][
    'key_name'] = parameter_types.name_with_leading_trailing_spaces
create_v20['properties']['server']['properties'][
    'security_groups']['items']['properties']['name'] = (
    parameter_types.name_with_leading_trailing_spaces)
create_v20['properties']['server']['properties']['user_data'] = {
    'oneOf': [
        {'type': 'string', 'format': 'base64', 'maxLength': 65535},
        {'type': 'null'},
    ],
}

create_v219 = copy.deepcopy(create)
create_v219['properties']['server'][
    'properties']['description'] = parameter_types.description

create_v232 = copy.deepcopy(create_v219)
create_v232['properties']['server'][
    'properties']['networks']['items'][
    'properties']['tag'] = parameter_types.tag
create_v232['properties']['server'][
    'properties']['block_device_mapping_v2']['items'][
    'properties']['tag'] = parameter_types.tag

# NOTE(artom) the following conditional was merged as
# "if version == '2.32'" The intent all along was to check whether
# version was greater than or equal to 2.32. In other words, we wanted
# to support tags in versions 2.32 and up, but ended up supporting them
# in version 2.32 only. Since we need a new microversion to add request
# body attributes, tags have been re-added in version 2.42.

# NOTE(gmann) Below schema 'create_v233' is added (builds on 2.19 schema)
# to keep the above mentioned behavior while merging the extension schema code
# into server schema file. Below is the ref code where BDM tag was originally
# got added for 2.32 microversion *only*.
# Ref- https://opendev.org/openstack/nova/src/commit/
#      9882a60e69a5ab8da314a199a56defc05098b743/nova/api/
#      openstack/compute/block_device_mapping.py#L71
create_v233 = copy.deepcopy(create_v219)
create_v233['properties']['server'][
    'properties']['networks']['items'][
    'properties']['tag'] = parameter_types.tag

# 2.37 builds on 2.32 and makes the following changes:
# 1. server.networks is required
# 2. server.networks is now either an enum or a list
# 3. server.networks.uuid is now required to be a uuid
create_v237 = copy.deepcopy(create_v233)
create_v237['properties']['server']['required'].append('networks')
create_v237['properties']['server']['properties']['networks'] = {
    'oneOf': [
        {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'fixed_ip': parameter_types.ip_address,
                    'port': {
                        'oneOf': [{'type': 'string', 'format': 'uuid'},
                                  {'type': 'null'}]
                    },
                    'uuid': {'type': 'string', 'format': 'uuid'},
                },
                'additionalProperties': False,
            },
        },
        {'type': 'string', 'enum': ['none', 'auto']},
    ],
}

# 2.42 builds on 2.37 and re-introduces the tag field to the list of network
# objects.
create_v242 = copy.deepcopy(create_v237)
create_v242['properties']['server']['properties']['networks'] = {
    'oneOf': [
        {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'fixed_ip': parameter_types.ip_address,
                    'port': {
                        'oneOf': [{'type': 'string', 'format': 'uuid'},
                                  {'type': 'null'}]
                    },
                    'uuid': {'type': 'string', 'format': 'uuid'},
                    'tag': parameter_types.tag,
                },
                'additionalProperties': False,
            },
        },
        {'type': 'string', 'enum': ['none', 'auto']},
    ],
}
create_v242['properties']['server'][
    'properties']['block_device_mapping_v2']['items'][
    'properties']['tag'] = parameter_types.tag

# 2.52 builds on 2.42 and makes the following changes:
# Allowing adding tags to instances when booting
create_v252 = copy.deepcopy(create_v242)
create_v252['properties']['server']['properties']['tags'] = {
    "type": "array",
    "items": parameter_types.tag,
    "maxItems": instance.MAX_TAG_COUNT
}

# 2.57 builds on 2.52 and removes the personality parameter.
create_v257 = copy.deepcopy(create_v252)
create_v257['properties']['server']['properties'].pop('personality')

# 2.63 builds on 2.57 and makes the following changes:
# Allowing adding trusted certificates to instances when booting
create_v263 = copy.deepcopy(create_v257)
create_v263['properties']['server']['properties'][
    'trusted_image_certificates'] = parameter_types.trusted_certs

# Add volume type in block_device_mapping_v2.
create_v267 = copy.deepcopy(create_v263)
create_v267['properties']['server']['properties'][
    'block_device_mapping_v2']['items'][
    'properties']['volume_type'] = parameter_types.volume_type

# Add host and hypervisor_hostname in server
create_v274 = copy.deepcopy(create_v267)
create_v274['properties']['server'][
    'properties']['host'] = parameter_types.fqdn
create_v274['properties']['server'][
    'properties']['hypervisor_hostname'] = parameter_types.fqdn

# Add hostname in server
create_v290 = copy.deepcopy(create_v274)
create_v290['properties']['server'][
    'properties']['hostname'] = parameter_types.hostname

# Support FQDN as hostname
create_v294 = copy.deepcopy(create_v290)
create_v294['properties']['server'][
    'properties']['hostname'] = parameter_types.fqdn

update = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'OS-DCF:diskConfig': parameter_types.disk_config,
                'accessIPv4': parameter_types.accessIPv4,
                'accessIPv6': parameter_types.accessIPv6,
            },
            'additionalProperties': False,
        },
    },
    'required': ['server'],
    'additionalProperties': False,
}

update_v20 = copy.deepcopy(update)
update_v20['properties']['server'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces

update_v219 = copy.deepcopy(update)
update_v219['properties']['server'][
    'properties']['description'] = parameter_types.description


update_v290 = copy.deepcopy(update_v219)
update_v290['properties']['server'][
    'properties']['hostname'] = parameter_types.hostname


update_v294 = copy.deepcopy(update_v290)
update_v294['properties']['server'][
    'properties']['hostname'] = parameter_types.fqdn

rebuild = {
    'type': 'object',
    'properties': {
        'rebuild': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'imageRef': parameter_types.image_id,
                'adminPass': parameter_types.admin_password,
                'metadata': parameter_types.metadata,
                'preserve_ephemeral': parameter_types.boolean,
                'OS-DCF:diskConfig': parameter_types.disk_config,
                'accessIPv4': parameter_types.accessIPv4,
                'accessIPv6': parameter_types.accessIPv6,
                'personality': parameter_types.personality,
            },
            'required': ['imageRef'],
            'additionalProperties': False,
        },
    },
    'required': ['rebuild'],
    'additionalProperties': False,
}

rebuild_v20 = copy.deepcopy(rebuild)
rebuild_v20['properties']['rebuild'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces

rebuild_v219 = copy.deepcopy(rebuild)
rebuild_v219['properties']['rebuild'][
    'properties']['description'] = parameter_types.description

rebuild_v254 = copy.deepcopy(rebuild_v219)
rebuild_v254['properties']['rebuild'][
    'properties']['key_name'] = parameter_types.name_or_none

# 2.57 builds on 2.54 and makes the following changes:
# 1. Remove the personality parameter.
# 2. Add the user_data parameter which is nullable so user_data can be reset.
rebuild_v257 = copy.deepcopy(rebuild_v254)
rebuild_v257['properties']['rebuild']['properties'].pop('personality')
rebuild_v257['properties']['rebuild']['properties']['user_data'] = ({
    'oneOf': [
        {'type': 'string', 'format': 'base64', 'maxLength': 65535},
        {'type': 'null'}
    ]
})

# 2.63 builds on 2.57 and makes the following changes:
# Allowing adding trusted certificates to instances when rebuilding
rebuild_v263 = copy.deepcopy(rebuild_v257)
rebuild_v263['properties']['rebuild']['properties'][
    'trusted_image_certificates'] = parameter_types.trusted_certs

rebuild_v290 = copy.deepcopy(rebuild_v263)
rebuild_v290['properties']['rebuild']['properties'][
    'hostname'] = parameter_types.hostname

rebuild_v294 = copy.deepcopy(rebuild_v290)
rebuild_v294['properties']['rebuild']['properties'][
    'hostname'] = parameter_types.fqdn

resize = {
    'type': 'object',
    'properties': {
        'resize': {
            'type': 'object',
            'properties': {
                'flavorRef': parameter_types.flavor_ref,
                'OS-DCF:diskConfig': parameter_types.disk_config,
            },
            'required': ['flavorRef'],
            'additionalProperties': False,
        },
    },
    'required': ['resize'],
    'additionalProperties': False,
}

create_image = {
    'type': 'object',
    'properties': {
        'createImage': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'metadata': parameter_types.metadata
            },
            'required': ['name'],
            'additionalProperties': False
        }
    },
    'required': ['createImage'],
    'additionalProperties': False
}

create_image_v20 = copy.deepcopy(create_image)
create_image_v20['properties']['createImage'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces

# TODO(stephenfin): Restrict the value to 'null' in a future API version
confirm_resize = {
    'type': 'object',
    'properties': {
        'confirmResize': {}
    },
    'required': ['confirmResize'],
    'additionalProperties': False
}

# TODO(stephenfin): Restrict the value to 'null' in a future API version
revert_resize = {
    'type': 'object',
    'properties': {
        'revertResize': {},
    },
    'required': ['revertResize'],
    'additionalProperties': False,
}

reboot = {
    'type': 'object',
    'properties': {
        'reboot': {
            'type': 'object',
            'properties': {
                'type': {
                    'type': 'string',
                    'enum': ['HARD', 'Hard', 'hard', 'SOFT', 'Soft', 'soft']
                }
            },
            'required': ['type'],
            'additionalProperties': False
        }
    },
    'required': ['reboot'],
    'additionalProperties': False
}

# TODO(stephenfin): Restrict the value to 'null' in a future API version
start_server = {
    'type': 'object',
    'properties': {
        'os-start': {},
    },
    'required': ['os-start'],
    'additionalProperties': False,
}

# TODO(stephenfin): Restrict the value to 'null' in a future API version
stop_server = {
    'type': 'object',
    'properties': {
        'os-stop': {},
    },
    'required': ['os-stop'],
    'additionalProperties': False,
}

trigger_crash_dump = {
    'type': 'object',
    'properties': {
        'trigger_crash_dump': {
            'type': 'null'
        }
    },
    'required': ['trigger_crash_dump'],
    'additionalProperties': False
}

JOINED_TABLE_QUERY_PARAMS_SERVERS = {
    'block_device_mapping': parameter_types.common_query_param,
    'services': parameter_types.common_query_param,
    'metadata': parameter_types.common_query_param,
    'system_metadata': parameter_types.common_query_param,
    'info_cache': parameter_types.common_query_param,
    'security_groups': parameter_types.common_query_param,
    'pci_devices': parameter_types.common_query_param
}

# These fields are valid values for sort_keys before we start
# using schema validation, but are considered to be bad values
# and disabled to use. In order to avoid backward incompatibility,
# they are ignored instead of return HTTP 400.
SERVER_LIST_IGNORE_SORT_KEY = [
    'architecture', 'cell_name', 'cleaned', 'default_ephemeral_device',
    'default_swap_device', 'deleted', 'deleted_at', 'disable_terminate',
    'ephemeral_gb', 'ephemeral_key_uuid', 'id', 'key_data', 'launched_on',
    'locked', 'memory_mb', 'os_type', 'reservation_id', 'root_gb',
    'shutdown_terminate', 'user_data', 'vcpus', 'vm_mode'
]

# From microversion 2.73 we start offering locked as a valid sort key.
SERVER_LIST_IGNORE_SORT_KEY_V273 = list(SERVER_LIST_IGNORE_SORT_KEY)
SERVER_LIST_IGNORE_SORT_KEY_V273.remove('locked')

VALID_SORT_KEYS = {
    "type": "string",
    "enum": ['access_ip_v4', 'access_ip_v6', 'auto_disk_config',
             'availability_zone', 'config_drive', 'created_at',
             'display_description', 'display_name', 'host', 'hostname',
             'image_ref', 'instance_type_id', 'kernel_id', 'key_name',
             'launch_index', 'launched_at', 'locked_by', 'node', 'power_state',
             'progress', 'project_id', 'ramdisk_id', 'root_device_name',
             'task_state', 'terminated_at', 'updated_at', 'user_id', 'uuid',
             'vm_state'] +
            SERVER_LIST_IGNORE_SORT_KEY
}

# We reuse the existing list and add locked to the list of valid sort keys.
VALID_SORT_KEYS_V273 = {
    "type": "string",
    "enum": ['locked'] + list(
            set(VALID_SORT_KEYS["enum"]) - set(SERVER_LIST_IGNORE_SORT_KEY)) +
            SERVER_LIST_IGNORE_SORT_KEY_V273
}

query_params_v21 = {
    'type': 'object',
    'properties': {
        'user_id': parameter_types.common_query_param,
        'project_id': parameter_types.common_query_param,
        # The alias of project_id. It should be removed in the
        # future with microversion bump.
        'tenant_id': parameter_types.common_query_param,
        'launch_index': parameter_types.common_query_param,
        # The alias of image. It should be removed in the
        # future with microversion bump.
        'image_ref': parameter_types.common_query_param,
        'image': parameter_types.common_query_param,
        'kernel_id': parameter_types.common_query_regex_param,
        'ramdisk_id': parameter_types.common_query_regex_param,
        'hostname': parameter_types.common_query_regex_param,
        'key_name': parameter_types.common_query_regex_param,
        'power_state': parameter_types.common_query_regex_param,
        'vm_state': parameter_types.common_query_param,
        'task_state': parameter_types.common_query_param,
        'host': parameter_types.common_query_param,
        'node': parameter_types.common_query_regex_param,
        'flavor': parameter_types.common_query_regex_param,
        'reservation_id': parameter_types.common_query_regex_param,
        'launched_at': parameter_types.common_query_regex_param,
        'terminated_at': parameter_types.common_query_regex_param,
        'availability_zone': parameter_types.common_query_regex_param,
        # NOTE(alex_xu): This is pattern matching, it didn't get any benefit
        # from DB index.
        'name': parameter_types.common_query_regex_param,
        # The alias of name. It should be removed in the future
        # with microversion bump.
        'display_name': parameter_types.common_query_regex_param,
        'description': parameter_types.common_query_regex_param,
        # The alias of description. It should be removed in the
        # future with microversion bump.
        'display_description': parameter_types.common_query_regex_param,
        'locked_by': parameter_types.common_query_regex_param,
        'uuid': parameter_types.common_query_param,
        'root_device_name': parameter_types.common_query_regex_param,
        'config_drive': parameter_types.common_query_regex_param,
        'access_ip_v4': parameter_types.common_query_regex_param,
        'access_ip_v6': parameter_types.common_query_regex_param,
        'auto_disk_config': parameter_types.common_query_regex_param,
        'progress': parameter_types.common_query_regex_param,
        'sort_key': multi_params(VALID_SORT_KEYS),
        'sort_dir': parameter_types.common_query_param,
        'all_tenants': parameter_types.common_query_param,
        'soft_deleted': parameter_types.common_query_param,
        'deleted': parameter_types.common_query_param,
        'status': parameter_types.common_query_param,
        'changes-since': multi_params({'type': 'string',
                                       'format': 'date-time'}),
        # NOTE(alex_xu): The ip and ip6 are implemented in the python.
        'ip': parameter_types.common_query_regex_param,
        'ip6': parameter_types.common_query_regex_param,
        'created_at': parameter_types.common_query_regex_param,
    },
    # For backward-compatible additionalProperties is set to be True here.
    # And we will either strip the extra params out or raise HTTP 400
    # according to the params' value in the later process.
    # This has been changed to False in microversion 2.75. From
    # microversion 2.75, no additional unknown parameter will be allowed.
    'additionalProperties': True,
    # Prevent internal-attributes that are started with underscore from
    # being striped out in schema validation, and raise HTTP 400 in API.
    'patternProperties': {"^_": parameter_types.common_query_param}
}

# Update the joined-table fields to the list so it will not be
# stripped in later process, thus can be handled later in api
# to raise HTTP 400.
query_params_v21['properties'].update(
    JOINED_TABLE_QUERY_PARAMS_SERVERS)

query_params_v21['properties'].update(
    parameter_types.pagination_parameters)

query_params_v226 = copy.deepcopy(query_params_v21)
query_params_v226['properties'].update({
    'tags': parameter_types.common_query_regex_param,
    'tags-any': parameter_types.common_query_regex_param,
    'not-tags': parameter_types.common_query_regex_param,
    'not-tags-any': parameter_types.common_query_regex_param,
})

query_params_v266 = copy.deepcopy(query_params_v226)
query_params_v266['properties'].update({
    'changes-before': multi_params({'type': 'string',
                                    'format': 'date-time'}),
})

query_params_v273 = copy.deepcopy(query_params_v266)
query_params_v273['properties'].update({
    'sort_key': multi_params(VALID_SORT_KEYS_V273),
    'locked': parameter_types.common_query_param,
})

# Microversion 2.75 makes query schema to disallow any invalid or unknown
# query parameters (filter or sort keys).
# *****Schema updates for microversion 2.75 start here*******
query_params_v275 = copy.deepcopy(query_params_v273)
# 1. Update sort_keys to allow only valid sort keys:
# NOTE(gmann): Remove the ignored sort keys now because 'additionalProperties'
# is False for query schema. Starting from miceoversion 2.75, API will
# raise 400 for any not-allowed sort keys instead of ignoring them.
VALID_SORT_KEYS_V275 = copy.deepcopy(VALID_SORT_KEYS_V273)
VALID_SORT_KEYS_V275['enum'] = list(
            set(VALID_SORT_KEYS_V273["enum"]) - set(
            SERVER_LIST_IGNORE_SORT_KEY_V273))
query_params_v275['properties'].update({
    'sort_key': multi_params(VALID_SORT_KEYS_V275),
})
# 2. Make 'additionalProperties' False.
query_params_v275['additionalProperties'] = False
# *****Schema updates for microversion 2.75 end here*******

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

resize_response = {
    'type': 'null',
}

confirm_resize_response = {
    'type': 'null',
}

revert_resize_response = {
    'type': 'null',
}

reboot_response = {
    'type': 'null',
}

start_server_response = {
    'type': 'null',
}

stop_server_response = {
    'type': 'null',
}

trigger_crash_dump_response = {
    'type': 'null',
}

create_image_response = {
    'type': 'null',
}

create_image_response_v245 = {
    'type': 'object',
    'properties': {
        'image_id': {'type': 'string', 'format': 'uuid'},
    },
    'required': ['image_id'],
    'additionalProperties': False,
}

rebuild_response = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                'accessIPv4': {
                    'type': 'string',
                    'oneOf': [
                        {'format': 'ipv4'},
                        {'const': ''},
                    ],
                },
                'accessIPv6': {
                    'type': 'string',
                    'oneOf': [
                        {'format': 'ipv6'},
                        {'const': ''},
                    ],
                },
                'addresses': {
                    'type': 'object',
                    'patternProperties': {
                        '^.+$': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'addr': {
                                        'type': 'string',
                                        'oneOf': [
                                            {'format': 'ipv4'},
                                            {'format': 'ipv6'},
                                        ],
                                    },
                                    'version': {
                                        'type': 'number',
                                        'enum': [4, 6],
                                    },
                                },
                                'required': [
                                    'addr',
                                    'version'
                                ],
                                'additionalProperties': False,
                            },
                        },
                    },
                    'additionalProperties': False,
                },
                'adminPass': {'type': ['null', 'string']},
                'created': {'type': 'string', 'format': 'date-time'},
                'fault': {
                    'type': 'object',
                    'properties': {
                        'code': {'type': 'integer'},
                        'created': {'type': 'string', 'format': 'date-time'},
                        'details': {'type': 'string'},
                        'message': {'type': 'string'},
                    },
                    'required': ['code', 'created', 'message'],
                    'additionalProperties': False,
                },
                'flavor': {
                    'type': 'object',
                    'properties': {
                        'id': {
                            'type': 'string',
                        },
                        'links': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'href': {
                                        'type': 'string',
                                        'format': 'uri',
                                    },
                                    'rel': {
                                        'type': 'string',
                                    },
                                },
                                'required': [
                                    'href',
                                    'rel'
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    'additionalProperties': False,
                },
                'hostId': {'type': 'string'},
                'id': {'type': 'string'},
                'image': {
                    'oneOf': [
                        {
                            'type': 'string',
                            'const': '',
                        },
                        {
                            'type': 'object',
                            'properties': {
                                'id': {
                                    'type': 'string'
                                },
                                'links': {
                                    'type': 'array',
                                    'items': {
                                        'type': 'object',
                                        'properties': {
                                            'href': {
                                                'type': 'string',
                                                'format': 'uri',
                                            },
                                            'rel': {
                                                'type': 'string',
                                            },
                                        },
                                        'required': [
                                            'href',
                                            'rel'
                                        ],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            'additionalProperties': False,
                        },
                    ],
                },
                'links': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'href': {
                                'type': 'string',
                                'format': 'uri',
                            },
                            'rel': {
                                'type': 'string',
                            },
                        },
                        'required': [
                            'href',
                            'rel'
                        ],
                        'additionalProperties': False,
                    },
                },
                'metadata': {
                    'type': 'object',
                    'patternProperties': {
                        '^.+$': {
                            'type': 'string'
                        },
                    },
                    'additionalProperties': False,
                },
                'name': {'type': ['string', 'null']},
                'progress': {'type': ['null', 'number']},
                'status': {'type': 'string'},
                'tenant_id': parameter_types.project_id,
                'updated': {'type': 'string', 'format': 'date-time'},
                'user_id': parameter_types.user_id,
                'OS-DCF:diskConfig': {'type': 'string'},
            },
            'required': [
                'accessIPv4',
                'accessIPv6',
                'addresses',
                'created',
                'flavor',
                'hostId',
                'id',
                'image',
                'links',
                'metadata',
                'name',
                'progress',
                'status',
                'tenant_id',
                'updated',
                'user_id',
                'OS-DCF:diskConfig',
            ],
            'additionalProperties': False,
        },
    },
    'required': [
        'server'
    ],
    'additionalProperties': False,
}

rebuild_response_v29 = copy.deepcopy(rebuild_response)
rebuild_response_v29['properties']['server']['properties']['locked'] = {
    'type': 'boolean',
}
rebuild_response_v29['properties']['server']['required'].append('locked')

rebuild_response_v219 = copy.deepcopy(rebuild_response_v29)
rebuild_response_v219['properties']['server']['properties']['description'] = {
    'type': ['null', 'string'],
}
rebuild_response_v219['properties']['server']['required'].append('description')

rebuild_response_v226 = copy.deepcopy(rebuild_response_v219)
rebuild_response_v226['properties']['server']['properties']['tags'] = {
    'type': 'array',
    'items': {
        'type': 'string',
    },
    'maxItems': 50,
}
rebuild_response_v226['properties']['server']['required'].append('tags')

# NOTE(stephenfin): We overwrite rather than extend 'flavor', since we now
# embed the flavor in this version
rebuild_response_v246 = copy.deepcopy(rebuild_response_v226)
rebuild_response_v246['properties']['server']['properties']['flavor'] = {
    'type': 'object',
    'properties': {
        'vcpus': {
            'type': 'integer',
        },
        'ram': {
            'type': 'integer',
        },
        'disk': {
            'type': 'integer',
        },
        'ephemeral': {
            'type': 'integer',
        },
        'swap': {
            'type': 'integer',
        },
        'original_name': {
            'type': 'string',
        },
        'extra_specs': {
            'type': 'object',
            'patternProperties': {
                '^.+$': {
                    'type': 'string'
                },
            },
            'additionalProperties': False,
        },
    },
    'required': ['vcpus', 'ram', 'disk', 'ephemeral', 'swap', 'original_name'],
    'additionalProperties': False,
}

rebuild_response_v254 = copy.deepcopy(rebuild_response_v246)
rebuild_response_v254['properties']['server']['properties']['key_name'] = {
    'type': ['null', 'string'],
}
rebuild_response_v254['properties']['server']['required'].append('key_name')

rebuild_response_v257 = copy.deepcopy(rebuild_response_v254)
rebuild_response_v257['properties']['server']['properties']['user_data'] = {
    'oneOf': [
        {'type': 'string', 'format': 'base64', 'maxLength': 65535},
        {'type': 'null'},
    ],
}
rebuild_response_v257['properties']['server']['required'].append('user_data')

rebuild_response_v263 = copy.deepcopy(rebuild_response_v257)
rebuild_response_v263['properties']['server']['properties'].update(
    {
        'trusted_image_certificates': {
            'type': ['array', 'null'],
            'items': {
                'type': 'string',
            },
        },
    },
)
rebuild_response_v263['properties']['server']['required'].append(
    'trusted_image_certificates'
)

rebuild_response_v271 = copy.deepcopy(rebuild_response_v263)
rebuild_response_v271['properties']['server']['properties'].update(
    {
        'server_groups': {
            'type': 'array',
            'items': {
                'type': 'string',
                'format': 'uuid',
            },
            'maxLength': 1,
        },
    },
)
rebuild_response_v271['properties']['server']['required'].append(
    'server_groups'
)

rebuild_response_v273 = copy.deepcopy(rebuild_response_v271)
rebuild_response_v273['properties']['server']['properties'].update(
    {
        'locked_reason': {
            'type': ['null', 'string'],
        },
    },
)
rebuild_response_v273['properties']['server']['required'].append(
    'locked_reason'
)

rebuild_response_v275 = copy.deepcopy(rebuild_response_v273)
rebuild_response_v275['properties']['server']['properties'].update(
    {
        'config_drive': {
            # TODO(stephenfin): Our tests return null but this shouldn't happen
            # in practice, apparently?
            'type': ['string', 'boolean', 'null'],
        },
        'OS-EXT-AZ:availability_zone': {
            'type': 'string',
        },
        'OS-EXT-SRV-ATTR:host': {
            'type': ['string', 'null'],
        },
        'OS-EXT-SRV-ATTR:hypervisor_hostname': {
            'type': ['string', 'null'],
        },
        'OS-EXT-SRV-ATTR:instance_name': {
            'type': 'string',
        },
        'OS-EXT-STS:power_state': {
            'type': 'integer',
            'enum': [0, 1, 3, 4, 6, 7],
        },
        'OS-EXT-STS:task_state': {
            'type': ['null', 'string'],
        },
        'OS-EXT-STS:vm_state': {
            'type': 'string',
        },
        'OS-EXT-SRV-ATTR:hostname': {
            'type': 'string',
        },
        'OS-EXT-SRV-ATTR:reservation_id': {
            'type': ['string', 'null'],
        },
        'OS-EXT-SRV-ATTR:launch_index': {
            'type': 'integer',
        },
        'OS-EXT-SRV-ATTR:kernel_id': {
            'type': ['string', 'null'],
        },
        'OS-EXT-SRV-ATTR:ramdisk_id': {
            'type': ['string', 'null'],
        },
        'OS-EXT-SRV-ATTR:root_device_name': {
            'type': ['string', 'null'],
        },
        'os-extended-volumes:volumes_attached': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {
                        'type': 'string',
                    },
                    'delete_on_termination': {
                        'type': 'boolean',
                        'default': False,
                    },
                },
                'required': ['id', 'delete_on_termination'],
                'additionalProperties': False,
            },
        },
        'OS-SRV-USG:launched_at': {
            'oneOf': [
                {'type': 'null'},
                {'type': 'string', 'format': 'date-time'},
            ],
        },
        'OS-SRV-USG:terminated_at': {
            'oneOf': [
                {'type': 'null'},
                {'type': 'string', 'format': 'date-time'},
            ],
        },
        'security_groups': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                    },
                },
                'required': ['name'],
                'additionalProperties': False,
            },
        },
        'host_status': {
            'type': 'string',
        },
    },
)
rebuild_response_v275['properties']['server']['required'].extend([
    'config_drive',
    'OS-EXT-AZ:availability_zone',
    'OS-EXT-STS:power_state',
    'OS-EXT-STS:task_state',
    'OS-EXT-STS:vm_state',
    'os-extended-volumes:volumes_attached',
    'OS-SRV-USG:launched_at',
    'OS-SRV-USG:terminated_at',
])
rebuild_response_v275['properties']['server']['properties']['addresses'][
    'patternProperties'
]['^.+$']['items']['properties'].update({
    'OS-EXT-IPS-MAC:mac_addr': {'type': 'string', 'format': 'mac-address'},
    'OS-EXT-IPS:type': {'type': 'string', 'enum': ['fixed', 'floating']},
})
rebuild_response_v275['properties']['server']['properties']['addresses'][
    'patternProperties'
]['^.+$']['items']['required'].extend([
    'OS-EXT-IPS-MAC:mac_addr', 'OS-EXT-IPS:type'
])

rebuild_response_v296 = copy.deepcopy(rebuild_response_v275)
rebuild_response_v296['properties']['server']['properties'].update({
    'pinned_availability_zone': {
        'type': ['null', 'string'],
    },
})
rebuild_response_v296['properties']['server']['required'].append(
    'pinned_availability_zone'
)
rebuild_response_v298 = copy.deepcopy(rebuild_response_v296)
rebuild_response_v298['properties']['server']['properties']['image'][
        'oneOf'][1]['properties'].update({
    'properties': {
        'type': 'object',
        'patternProperties': {
            '^[a-zA-Z0-9_:. ]{1,255}$': {
                'type': 'string',
                'max_Length': 255,
                },
            },
            'additionalProperties': False,
    },
})

rebuild_response_v2100 = copy.deepcopy(rebuild_response_v298)
rebuild_response_v2100['properties']['server']['properties'].update({
    'scheduler_hints': _hints,
})
rebuild_response_v2100['properties']['server']['required'].append(
    'scheduler_hints'
)
