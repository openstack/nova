==========
Extensions
==========

Extensions are a deprecated concept in Nova. Support for extensions will be
removed in a future release. In order to keep backwards-compatibility with
legacy V2 API users, the ``extension_info`` API will remain as part of the
Compute API. However, API extensions will not be supported anymore;
there is only one standard API now. For the current V2.1 API, ``Microversions``
are the new mechanism for implementing API features and changes. For more
detail about microversions, please refer to :doc:`microversions`.
