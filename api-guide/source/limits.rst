======
Limits
======

Accounts may be pre-configured with a set of thresholds (or limits) to
manage capacity and prevent abuse of the system. The system recognizes
*absolute limits*. Absolute limits are fixed. Limits are configured by
operators and may differ from one deployment of the OpenStack Compute service
to another. Please contact your provider to determine the limits that
apply to your account. Your provider may be able to adjust your
account's limits if they are too low. Also see the API Reference for
`Limits <https://developer.openstack.org/api-ref/compute/#limits-limits>`__.

Absolute limits
~~~~~~~~~~~~~~~

Absolute limits are specified as name/value pairs. The name of the
absolute limit uniquely identifies the limit within a deployment. Please
consult your provider for an exhaustive list of absolute limits names. An
absolute limit value is always specified as an integer. The name of the
absolute limit determines the unit type of the integer value. For
example, the name maxServerMeta implies that the value is in terms of
server metadata items.

**Table: Sample absolute limits**

+-------------------+-------------------+------------------------------------+
| Name              | Value             | Description                        |
+-------------------+-------------------+------------------------------------+
| maxTotalRAMSize   | 51200             | Maximum total amount of RAM (MB)   |
+-------------------+-------------------+------------------------------------+
| maxServerMeta     | 5                 | Maximum number of metadata items   |
|                   |                   | associated with a server.          |
+-------------------+-------------------+------------------------------------+
| maxImageMeta      | 5                 | Maximum number of metadata items   |
|                   |                   | associated with an image.          |
+-------------------+-------------------+------------------------------------+
| maxPersonality    | 5                 | The maximum number of file         |
|                   |                   | path/content pairs that can be     |
|                   |                   | supplied on server build.          |
+-------------------+-------------------+------------------------------------+
| maxPersonalitySize| 10240             | The maximum size, in bytes, for    |
|                   |                   | each personality file.             |
+-------------------+-------------------+------------------------------------+


Determine limits programmatically
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Applications can programmatically determine current account limits. For
information, see
`Limits <https://developer.openstack.org/api-ref/compute/#limits-limits>`__.
