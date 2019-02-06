.. -*- rst -*-

======================================================
 Flavors extra-specs (flavors, os-flavor-extra-specs)
======================================================

Lists, creates, deletes, and updates the extra-specs or keys for a
flavor.

Refer to `Compute Flavors
<https://docs.openstack.org/nova/latest/user/flavors.html#extra-specs>`__
for available built-in extra specs.

List Extra Specs For A Flavor
=============================

.. rest_method:: GET /flavors/{flavor_id}/os-extra_specs

Lists all extra specs for a flavor, by ID.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - flavor_id: flavor_id

Response
--------


.. rest_parameters:: parameters.yaml

  - extra_specs: extra_specs
  - key: flavor_extra_spec_key2
  - value: flavor_extra_spec_value

**Example List Extra Specs For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-list-resp.json
   :language: javascript

Create Extra Specs For A Flavor
===============================

.. rest_method:: POST /flavors/{flavor_id}/os-extra_specs

Creates extra specs for a flavor, by ID.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - flavor_id: flavor_id
  - extra_specs: extra_specs
  - key: flavor_extra_spec_key2
  - value: flavor_extra_spec_value

**Example Create Extra Specs For A Flavor: JSON request**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - extra_specs: extra_specs
  - key: flavor_extra_spec_key2
  - value: flavor_extra_spec_value

**Example Create Extra Specs For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-create-resp.json
   :language: javascript

Show An Extra Spec For A Flavor
===============================

.. rest_method:: GET /flavors/{flavor_id}/os-extra_specs/{flavor_extra_spec_key}

Shows an extra spec, by key, for a flavor, by ID.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - flavor_id: flavor_id
  - flavor_extra_spec_key: flavor_extra_spec_key


Response
--------

.. rest_parameters:: parameters.yaml

  - key: flavor_extra_spec_key2
  - value: flavor_extra_spec_value

**Example Show An Extra Spec For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-get-resp.json
   :language: javascript

Update An Extra Spec For A Flavor
=================================

.. rest_method:: PUT /flavors/{flavor_id}/os-extra_specs/{flavor_extra_spec_key}

Updates an extra spec, by key, for a flavor, by ID.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - flavor_id: flavor_id
  - flavor_extra_spec_key: flavor_extra_spec_key
  - key: flavor_extra_spec_key2
  - value: flavor_extra_spec_value


**Example Update An Extra Spec For A Flavor: JSON request**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-update-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml


  - key: flavor_extra_spec_key2
  - value: flavor_extra_spec_value

**Example Update An Extra Spec For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-update-resp.json
   :language: javascript

Delete An Extra Spec For A Flavor
=================================

.. rest_method:: DELETE /flavors/{flavor_id}/os-extra_specs/{flavor_extra_spec_key}

Deletes an extra spec, by key, for a flavor, by ID.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - flavor_id: flavor_id
  - flavor_extra_spec_key: flavor_extra_spec_key

Response
--------

There is no body content for the response of a successful DELETE action.
