.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

=====================================
 Root certificates (os-certificates)
=====================================

Creates and shows details for a root certificate.

Create Certificate
==================

.. rest_method:: POST /os-certificates

Creates a certificate.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example Create Certificate: JSON response**

.. literalinclude:: ../../doc/api_samples/os-certificates/certificate-create-resp.json
   :language: javascript

Show Certificate Details
========================

.. rest_method:: GET /os-certificates/{certificate_id}

Shows details for a certificate.

Normal response codes: 200

Error response codes: notImplemented(501), unauthorized(401),
forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - certificate_id: certificate_id

Response
--------

**Example Show Certificate Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-certificates/certificate-get-root-resp.json
   :language: javascript
