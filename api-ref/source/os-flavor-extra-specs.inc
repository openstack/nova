.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

======================================================
 Flavors extra-specs (flavors, os-flavor-extra-specs)
======================================================

Lists, creates, deletes, and updates the extra-specs or keys for a
flavor.

Create Extra Specs For A Flavor
===============================

.. rest_method:: POST /v2.1/{tenant_id}/flavors/{flavor_id}/os-extra_specs

Creates extra specs for a flavor, by ID.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id

**Example Create Extra Specs For A Flavor: JSON request**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-create-req.json
   :language: javascript

Response
--------

**Example Create Extra Specs For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-create-resp.json
   :language: javascript

List Extra Specs For A Flavor
=============================

.. rest_method:: GET /v2.1/{tenant_id}/flavors/{flavor_id}/os-extra_specs

Lists all extra specs for a flavor, by ID.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id

Response
--------

**Example List Extra Specs For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-list-resp.json
   :language: javascript

Show An Extra Spec For A Flavor
===============================

.. rest_method:: GET /v2.1/{tenant_id}/flavors/{flavor_id}/os-extra_specs/{flavor_extra_spec_key}

Shows an extra spec, by key, for a flavor, by ID.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id
  - flavor_extra_spec_key: flavor_extra_spec_key

Response
--------

**Example Show An Extra Spec For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-get-resp.json
   :language: javascript

Update An Extra Spec For A Flavor
=================================

.. rest_method:: PUT /v2.1/{tenant_id}/flavors/{flavor_id}/os-extra_specs/{flavor_extra_spec_key}

Updates an extra spec, by key, for a flavor, by ID.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id
  - flavor_extra_spec_key: flavor_extra_spec_key

**Example Update An Extra Spec For A Flavor: JSON request**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-update-req.json
   :language: javascript

Response
--------

**Example Update An Extra Spec For A Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-extra-specs/flavor-extra-specs-update-resp.json
   :language: javascript

Delete An Extra Spec For A Flavor
=================================

.. rest_method:: DELETE /v2.1/{tenant_id}/flavors/{flavor_id}/os-extra_specs/{flavor_extra_spec_key}

Deletes an extra spec, by key, for a flavor, by ID.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id
  - flavor_extra_spec_key: flavor_extra_spec_key

Response
--------

