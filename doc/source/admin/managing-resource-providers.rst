==============================================
Managing Resource Providers Using Config Files
==============================================

In order to facilitate management of resource provider information in the
Placement API, Nova provides `a method`__ for admins to add custom inventory
and traits to resource providers using YAML files.

__ https://specs.openstack.org/openstack/nova-specs/specs/ussuri/approved/provider-config-file.html

.. note::

    Only ``CUSTOM_*`` resource classes and traits may be managed this way.

Placing Files
-------------

Nova-compute will search for ``*.yaml`` files in the path specified in
:oslo.config:option:`compute.provider_config_location`. These files will be
loaded and validated for errors on nova-compute startup. If there are any
errors in the files, nova-compute will fail to start up.

Administrators should ensure that provider config files have appropriate
permissions and ownership. See the `specification`__ and `admin guide`__
for more details.

__ https://specs.openstack.org/openstack/nova-specs/specs/ussuri/approved/provider-config-file.html
__ https://docs.openstack.org/nova/latest/admin/managing-resource-providers.html

.. note::

    The files are loaded once at nova-compute startup and any changes or new
    files will not be recognized until the next nova-compute startup.

Examples
--------

Resource providers to target can be identified by either UUID or name. In
addition, the value ``$COMPUTE_NODE`` can be used in the UUID field to
identify all nodes managed by the service.

If an entry does not include any additional inventory or traits, it will be
logged at load time but otherwise ignored. In the case of a resource provider
being identified by both ``$COMPUTE_NODE`` and individual UUID/name, the
values in the ``$COMPUTE_NODE`` entry will be ignored for *that provider* only
if the explicit entry includes inventory or traits.

.. note::

    In the case that a resource provider is identified more than once by
    explicit UUID/name, the nova-compute service will fail to start. This
    is a global requirement across all supplied ``provider.yaml`` files.

.. code-block:: yaml

    meta:
      schema_version: '1.0'
    providers:
      - identification:
          name: 'EXAMPLE_RESOURCE_PROVIDER'
          # Additional valid identification examples:
          # uuid: '$COMPUTE_NODE'
          # uuid: '5213b75d-9260-42a6-b236-f39b0fd10561'
        inventories:
          additional:
            - CUSTOM_EXAMPLE_RESOURCE_CLASS:
                total: 100
                reserved: 0
                min_unit: 1
                max_unit: 10
                step_size: 1
                allocation_ratio: 1.0
        traits:
          additional:
            - 'CUSTOM_EXAMPLE_TRAIT'

Schema Example
--------------
.. code-block:: yaml

  type: object
  properties:
    # This property is used to track where the provider.yaml file originated.
    # It is reserved for internal use and should never be set in a provider.yaml
    # file supplied by an end user.
    __source_file:
      not: {}
    meta:
      type: object
      properties:
        # Version ($Major, $minor) of the schema must successfully parse
        # documents conforming to ($Major, 0..N). Any breaking schema change
        # (e.g. removing fields, adding new required fields, imposing a stricter
        # pattern on a value, etc.) must bump $Major.
        schema_version:
          type: string
          pattern: '^1\.([0-9]|[1-9][0-9]+)$'
      required:
        - schema_version
      additionalProperties: true
    providers:
      type: array
      items:
        type: object
        properties:
          identification:
            $ref: '#/provider_definitions/provider_identification'
          inventories:
            $ref: '#/provider_definitions/provider_inventories'
          traits:
            $ref: '#/provider_definitions/provider_traits'
        required:
          - identification
        additionalProperties: true
  required:
    - meta
  additionalProperties: true

  provider_definitions:
    provider_identification:
      # Identify a single provider to configure. Exactly one identification
      # method should be used. Currently `uuid` or `name` are supported, but
      # future versions may support others.
      # The uuid can be set to the sentinel value `$COMPUTE_NODE` which will
      # cause the consuming compute service to apply the configuration to
      # to all compute node root providers it manages that are not otherwise
      # specified using a uuid or name.
      type: object
      properties:
        uuid:
          oneOf:
              # TODO(sean-k-mooney): replace this with type uuid when we can depend
              # on a version of the jsonschema lib that implements draft 8 or later
              # of the jsonschema spec.
            - type: string
              pattern: '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'
            - type: string
              const: '$COMPUTE_NODE'
        name:
          type: string
          minLength: 1
      # This introduces the possibility of an unsupported key name being used to
      # get by schema validation, but is necessary to support forward
      # compatibility with new identification methods. This should be checked
      # after schema validation.
      minProperties: 1
      maxProperties: 1
      additionalProperties: false
    provider_inventories:
      # Allows the admin to specify various adjectives to create and manage
      # providers' inventories. This list of adjectives can be extended in the
      # future as the schema evolves to meet new use cases. As of v1.0, only one
      # adjective, `additional`, is supported.
      type: object
      properties:
        additional:
          type: array
          items:
            patternProperties:
              # Allows any key name matching the resource class pattern,
              # check to prevent conflicts with virt driver owned resouces classes
              # will be done after schema validation.
              ^[A-Z0-9_]{1,255}$:
                type: object
                properties:
                  # Any optional properties not populated will be given a default value by
                  # placement. If overriding a pre-existing provider values will not be
                  # preserved from the existing inventory.
                  total:
                    type: integer
                  reserved:
                    type: integer
                  min_unit:
                    type: integer
                  max_unit:
                    type: integer
                  step_size:
                    type: integer
                  allocation_ratio:
                    type: number
                required:
                  - total
                # The defined properties reflect the current placement data
                # model. While defining those in the schema and not allowing
                # additional properties means we will need to bump the schema
                # version if they change, that is likely to be part of a large
                # change that may have other impacts anyway. The benefit of
                # stricter validation of property names outweighs the (small)
                # chance of having to bump the schema version as described above.
                additionalProperties: false
            # This ensures only keys matching the pattern above are allowed
            additionalProperties: false
      additionalProperties: true
    provider_traits:
      # Allows the admin to specify various adjectives to create and manage
      # providers' traits. This list of adjectives can be extended in the
      # future as the schema evolves to meet new use cases. As of v1.0, only one
      # adjective, `additional`, is supported.
      type: object
      properties:
        additional:
          type: array
          items:
            # Allows any value matching the trait pattern here, additional
            # validation will be done after schema validation.
            type: string
            pattern: '^[A-Z0-9_]{1,255}$'
      additionalProperties: true

.. note::

    When creating a ``provider.yaml`` config file it is recommended to use the
    schema provided by nova to validate the config using a simple jsonschema
    validator rather than starting the nova compute agent to enable faster
    iteration.

