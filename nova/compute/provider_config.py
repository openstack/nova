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

import glob
import jsonschema
import logging
import microversion_parse
import os
import yaml

import os_resource_classes
import os_traits

from nova import exception as nova_exc
from nova.i18n import _

LOG = logging.getLogger(__name__)

# A dictionary with keys for all supported major versions with lists of
# corresponding minor versions as values.
SUPPORTED_SCHEMA_VERSIONS = {
    1: {0}
}

# Supported provider config file schema
SCHEMA_V1 = {
    # This defintion uses JSON Schema Draft 7.
    # https://json-schema.org/draft-07/json-schema-release-notes.html
    'type': 'object',
    'properties': {
        # This property is used to track where the provider.yaml file
        # originated. It is reserved for internal use and should never be
        # set in a provider.yaml file supplied by an end user.
        '__source_file': {'not': {}},
        'meta': {
            'type': 'object',
            'properties': {
                # Version ($Major, $minor) of the schema must successfully
                # parse documents conforming to ($Major, 0..N).
                # Any breaking schema change (e.g. removing fields, adding
                # new required fields, imposing a stricter pattern on a value,
                # etc.) must bump $Major.
                'schema_version': {
                    'type': 'string',
                    'pattern': '^1.([0-9]|[1-9][0-9]+)$'
                }
            },
            'required': ['schema_version'],
            'additionalProperties': True
        },
        'providers': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'identification': {
                        '$ref': '#/$defs/providerIdentification'
                    },
                    'inventories': {
                        '$ref': '#/$defs/providerInventories'
                    },
                    'traits': {
                        '$ref': '#/$defs/providerTraits'
                    }
                },
                'required': ['identification'],
                'additionalProperties': True
            }
        }
    },
    'required': ['meta'],
    'additionalProperties': True,
    '$defs': {
        'providerIdentification': {
            # Identify a single provider to configure.
            # Exactly one identification method should be used. Currently
            # `uuid` or `name` are supported, but future versions may
            # support others. The uuid can be set to the sentinel value
            # `$COMPUTE_NODE` which will cause the consuming compute service to
            # apply the configuration to all compute node root providers
            # it manages that are not otherwise specified using a uuid or name.
            'type': 'object',
            'properties': {
                'uuid': {
                    'oneOf': [
                        {
                            # TODO(sean-k-mooney): replace this with type uuid
                            # when we can depend on a version of the jsonschema
                            # lib that implements draft 8 or later of the
                            # jsonschema spec.
                            'type': 'string',
                            'pattern':
                                '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-'
                                '[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-'
                                '[0-9A-Fa-f]{12}$'
                        },
                        {
                            'type': 'string',
                            'const': '$COMPUTE_NODE'
                        }
                    ]
                },
                'name': {
                    'type': 'string',
                    'minLength': 1,
                    'maxLength': 200
                }
            },
            # This introduces the possibility of an unsupported key name being
            # used to get by schema validation, but is necessary to support
            # forward compatibility with new identification methods.
            # This should be checked after schema validation.
            'minProperties': 1,
            'maxProperties': 1,
            'additionalProperties': False
        },
        'providerInventories': {
            # Allows the admin to specify various adjectives to create and
            # manage providers' inventories. This list of adjectives can be
            # extended in the future as the schema evolves to meet new use
            # cases. As of v1.0, only one adjective, `additional`, is
            # supported.
            'type': 'object',
            'properties': {
                'additional': {
                    'type': 'array',
                    'items': {
                        'patternProperties': {
                            # Allows any key name matching the resource class
                            # pattern, check to prevent conflicts with virt
                            # driver owned resouces classes will be done after
                            # schema validation.
                            '^[A-Z0-9_]{1,255}$': {
                                'type': 'object',
                                'properties': {
                                    # Any optional properties not populated
                                    # will be given a default value by
                                    # placement. If overriding a pre-existing
                                    # provider values will not be preserved
                                    # from the existing inventory.
                                    'total': {
                                        'type': 'integer'
                                    },
                                    'reserved': {
                                        'type': 'integer'
                                    },
                                    'min_unit': {
                                        'type': 'integer'
                                    },
                                    'max_unit': {
                                        'type': 'integer'
                                    },
                                    'step_size': {
                                        'type': 'integer'
                                    },
                                    'allocation_ratio': {
                                        'type': 'number'
                                    }
                                },
                                'required': ['total'],
                                # The defined properties reflect the current
                                # placement data model. While defining those
                                # in the schema and not allowing additional
                                # properties means we will need to bump the
                                # schema version if they change, that is likely
                                # to be part of a large change that may have
                                # other impacts anyway. The benefit of stricter
                                # validation of property names outweighs the
                                # (small) chance of having to bump the schema
                                # version as described above.
                                'additionalProperties': False
                            }
                        },
                        # This ensures only keys matching the pattern
                        # above are allowed.
                        'additionalProperties': False
                    }
                }
            },
            'additionalProperties': True
        },
        'providerTraits': {
            # Allows the admin to specify various adjectives to create and
            # manage providers' traits. This list of adjectives can be extended
            # in the future as the schema evolves to meet new use cases.
            # As of v1.0, only one adjective, `additional`, is supported.
            'type': 'object',
            'properties': {
                'additional': {
                    'type': 'array',
                    'items': {
                        # Allows any value matching the trait pattern here,
                        # additional validation will be done after schema
                        # validation.
                        'type': 'string',
                        'pattern': '^[A-Z0-9_]{1,255}$'
                    }
                }
            },
            'additionalProperties': True
        }
    }
}


def _load_yaml_file(path):
    """Loads and parses a provider.yaml config file into a dict.

    :param path: Path to the yaml file to load.
    :return: Dict representing the yaml file requested.
    :raise: ProviderConfigException if the path provided cannot be read
            or the file is not valid yaml.
    """
    try:
        with open(path) as open_file:
            try:
                return yaml.safe_load(open_file)
            except yaml.YAMLError as ex:
                message = _("Unable to load yaml file: %s ") % ex
                if hasattr(ex, 'problem_mark'):
                    pos = ex.problem_mark
                    message += _("File: %s ") % open_file.name
                    message += _("Error position: (%s:%s)") % (
                        pos.line + 1, pos.column + 1)
                raise nova_exc.ProviderConfigException(error=message)
    except OSError:
        message = _("Unable to read yaml config file: %s") % path
        raise nova_exc.ProviderConfigException(error=message)


def _validate_provider_config(config, provider_config_path):
    """Accepts a schema-verified provider config in the form of a dict and
     performs additional checks for format and required keys.

    :param config: Dict containing a provider config file
    :param provider_config_path: Path to the provider config, used for logging
    :return: List of valid providers
    :raise nova.exception.ProviderConfigException: If provider id is missing,
        or a resource class or trait name is invalid.
    """
    def _validate_traits(provider):
        # Check that traits are custom
        additional_traits = set(provider.get("traits", {}).get(
            "additional", []))
        trait_conflicts = [trait for trait in additional_traits
                           if not os_traits.is_custom(trait)]
        if trait_conflicts:
            # sort for more predictable message for testing
            message = _(
                "Invalid traits, only custom traits are allowed: %s"
            ) % sorted(trait_conflicts)
            raise nova_exc.ProviderConfigException(error=message)
        return additional_traits

    def _validate_rc(provider):
        # Check that resource classes are custom
        additional_inventories = provider.get("inventories", {}).get(
            "additional", [])
        all_inventory_conflicts = []
        for inventory in additional_inventories:
            inventory_conflicts = [rc for rc in inventory
                                   if not os_resource_classes.is_custom(rc)]
            all_inventory_conflicts += inventory_conflicts

        if all_inventory_conflicts:
            # sort for more predictable message for testing
            message = _(
                "Invalid resource class, only custom resource classes "
                "are allowed: %s") % ', '.join(sorted(all_inventory_conflicts))
            raise nova_exc.ProviderConfigException(error=message)
        return additional_inventories

    # store valid providers
    valid_providers = []

    for provider in config.get("providers", []):
        # Check that the identification method is known since
        # the schema only requires that some property be present
        pid = provider["identification"]
        provider_id = pid.get("name") or pid.get("uuid")
        # Not checking the validity of provider_id since
        # the schema has already ensured that.

        additional_traits = _validate_traits(provider)
        additional_inventories = _validate_rc(provider)

        # filter out no-op providers so they will not be returned
        if not additional_traits and not additional_inventories:
            message = (
                "Provider %(provider_id)s defined in %(provider_config_path)s "
                "has no additional inventories or traits and will be ignored."
            ) % {
                "provider_id": provider_id,
                "provider_config_path": provider_config_path
            }
            LOG.warning(message)
        else:
            valid_providers.append(provider)

    return valid_providers


def _parse_provider_yaml(path):
    """Loads schema, parses a provider.yaml file and validates the content.

    :param path: File system path to the file to parse.
    :return: dict representing the contents of the file.
    :raise ProviderConfigException: If the specified file does
        not validate against the schema, the schema version is not supported,
        or if unable to read configuration or schema files.
    """
    yaml_file = _load_yaml_file(path)

    try:
        schema_version = microversion_parse.parse_version_string(
            yaml_file['meta']['schema_version'])
    except (KeyError, TypeError):
        message = _("Unable to detect schema version: %s") % yaml_file
        raise nova_exc.ProviderConfigException(error=message)

    if schema_version.major not in SUPPORTED_SCHEMA_VERSIONS:
        message = _(
            "Unsupported schema major version: %d") % schema_version.major
        raise nova_exc.ProviderConfigException(error=message)

    if schema_version.minor not in \
            SUPPORTED_SCHEMA_VERSIONS[schema_version.major]:
        # TODO(sean-k-mooney): We should try to provide a better
        # message that identifies which fields may be ignored
        # and the max minor version supported by this version of nova.
        message = (
            "Provider config file [%(path)s] is at schema version "
            "%(schema_version)s. Nova supports the major version, "
            "but not the minor. Some fields may be ignored."
            % {"path": path, "schema_version": schema_version})
        LOG.warning(message)

    try:
        jsonschema.validate(yaml_file, SCHEMA_V1)
    except jsonschema.exceptions.ValidationError as e:
        message = _(
            "The provider config file %(path)s did not pass validation "
            "for schema version %(schema_version)s: %(reason)s") % {
                "path": path, "schema_version": schema_version, "reason": e}
        raise nova_exc.ProviderConfigException(error=message)
    return yaml_file


def get_provider_configs(provider_config_dir):
    """Gathers files in the provided path and calls the parser for each file
    and merges them into a list while checking for a number of possible
    conflicts.

    :param provider_config_dir: Path to a directory containing provider config
        files to be loaded.
    :raise nova.exception.ProviderConfigException: If unable to read provider
        config directory or if one of a number of validation checks fail:
        - Unknown, unsupported, or missing schema major version.
        - Unknown, unsupported, or missing resource provider identification.
        - A specific resource provider is identified twice with the same
          method. If the same provider identified by *different* methods,
          such conflict will be detected in a later stage.
        - A resource class or trait name is invalid or not custom.
        - A general schema validation error occurs (required fields,
          types, etc).
    :return: A dict of dicts keyed by uuid_or_name with the parsed and
    validated contents of all files in the provided dir. Each value in the dict
    will include the source file name the value of the __source_file key.
    """
    provider_configs = {}

    provider_config_paths = glob.glob(
        os.path.join(provider_config_dir, "*.yaml"))
    provider_config_paths.sort()

    if not provider_config_paths:
        message = (
            "No provider configs found in %s. If files are present, "
            "ensure the Nova process has access."
        )
        LOG.info(message, provider_config_dir)

        # return an empty dict as no provider configs found
        return provider_configs

    for provider_config_path in provider_config_paths:
        provider_config = _parse_provider_yaml(provider_config_path)

        for provider in _validate_provider_config(
            provider_config, provider_config_path,
        ):
            provider['__source_file'] = os.path.basename(provider_config_path)
            pid = provider["identification"]
            uuid_or_name = pid.get("uuid") or pid.get("name")
            # raise exception if this provider was already processed
            if uuid_or_name in provider_configs:
                raise nova_exc.ProviderConfigException(
                    error=_(
                        "Provider %(provider_id)s has multiple definitions "
                        "in source file(s): %(source_files)s."
                    ) % {
                        "provider_id": uuid_or_name,
                        # sorted set for deduplication and consistent order
                        "source_files": sorted({
                            provider_configs[uuid_or_name]["__source_file"],
                            provider_config_path
                        })
                    }
                )
            provider_configs[uuid_or_name] = provider
    return provider_configs
