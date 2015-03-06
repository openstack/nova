REST API VERSION HISTORY
========================

This documents the changes made to the REST API with every
microversion change. The description for each version should be a
verbose one which has enough information to be suitable for use in
user documentation.

- **2.1**

  This is the initial version of the v2.1 API which supports
  microversions. The V2.1 API is from the REST API users's point of
  view exactly the same as v2.0 except with strong input validation.

  A user can specify a header in the API request:

  X-OpenStack-Nova-API-Version: <version>

  where <version> is any valid api version for this API.

  If no version is specified then the API will behave as if a version
  request of v2.1 was requested.

- **2.2**

  Added Keypair type.

  A user can request the creation of a certain 'type' of keypair (ssh or x509)
  in the os-keypairs plugin

  If no keypair type is specified, then the default 'ssh' type of keypair is
  created.

  Fixes status code for os-keypairs create method from 200 to 201

  Fixes status code for os-keypairs delete method from 202 to 204

- **2.3**

  Exposed additional attributes in os-extended-server-attributes:
  reservation_id, launch_index, ramdisk_id, kernel_id, hostname,
  root_device_name, userdata.

  Exposed delete_on_termination for attached_volumes in os-extended-volumes.

  This change is required for the extraction of EC2 API into a standalone
  service. It exposes necessary properties absent in public nova APIs yet.
  Add info for Standalone EC2 API to cut access to Nova DB.
