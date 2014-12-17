======
Limits
======

Accounts may be pre-configured with a set of thresholds (or limits) to
manage capacity and prevent abuse of the system. The system recognizes
two kinds of limits: *rate limits* and *absolute limits*. Rate limits
are thresholds that are reset after a certain amount of time passes.
Absolute limits are fixed. Limits are configured by operators and may
differ from one deployment of the OpenStack Compute service to
another.  Please contact your provider to determine the limits that
apply to your account. Your provider may be able to adjust your
account's limits if they are too low. Also see the API Reference for
`*Limits* <http://developer.openstack.org/api-ref-compute-v2.html#compute_limits>`__.

Rate limits
~~~~~~~~~~~

Rate limits are specified in terms of both a human-readable wild-card
URI and a machine-processable regular expression. The human-readable
limit is intended for displaying in graphical user interfaces. The
machine-processable form is intended to be used directly by client
applications.

The regular expression boundary matcher "^" for the rate limit takes
effect after the root URI path. For example, the regular expression
^/servers would match the bolded portion of the following URI:
https://servers.api.openstack.org/v2/3542812\ **/servers**.

**Table: Sample rate limits**

+------------+-------------------+----------------------+----------+
| Verb       | URI               | RegEx                | Default  |
+------------+-------------------+----------------------+----------+
| **POST**   | \*                | .\*                  | 120/min  |
+------------+-------------------+----------------------+----------+
| **POST**   | \*/servers        | ^/servers            | 120/min  |
+------------+-------------------+----------------------+----------+
| **PUT**    | \*                | .\*                  | 120/min  |
+------------+-------------------+----------------------+----------+
| **GET**    | \*changes-since\* | .\*changes-since.\*  | 120/min  |
+------------+-------------------+----------------------+----------+
| **DELETE** | \*                | .\*                  | 120/min  |
+------------+-------------------+----------------------+----------+
| **GET**    | \*/os-fping\*     | ^/os-fping           | 12/min   |
+------------+-------------------+----------------------+----------+


Rate limits are applied in order relative to the verb, going from least
to most specific.

In the event a request exceeds the thresholds established for your
account, a 413 HTTP response is returned with a ``Retry-After`` header
to notify the client when they can attempt to try again.

Absolute limits
~~~~~~~~~~~~~~~

Absolute limits are specified as name/value pairs. The name of the
absolute limit uniquely identifies the limit within a deployment. Please
consult your provider for an exhaustive list of absolute value names. An
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
`*Limits* <http://developer.openstack.org/api-ref-compute-v2.html#compute_limits>`__.
