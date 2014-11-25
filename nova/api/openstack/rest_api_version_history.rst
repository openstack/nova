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

  X-OpenStack-Compute-API-Version: <version>

  where <version> is any valid api version for this API.

  If no version is specified then the API will behave as if a version
  request of v2.1 was requested.
