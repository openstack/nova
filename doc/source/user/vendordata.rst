Vendordata
==========

Nova presents configuration information to instances it starts via a mechanism
called metadata. This metadata is made available via either a configdrive, or
the metadata service. These mechanisms are widely used via helpers such as
cloud-init to specify things like the root password the instance should use.
There are three separate groups of people who need to be able to specify
metadata for an instance.

User provided data
------------------

The user who booted the instance can pass metadata to the instance in several
ways. For authentication keypairs, the keypairs functionality of the Nova APIs
can be used to upload a key and then specify that key during the Nova boot API
request. For less structured data, a small opaque blob of data may be passed
via the user-data feature of the Nova API. Examples of such unstructured data
would be the puppet role that the instance should use, or the HTTP address of a
server to fetch post-boot configuration information from.

Nova provided data
------------------

Nova itself needs to pass information to the instance via its internal
implementation of the metadata system. Such information includes the network
configuration for the instance, as well as the requested hostname for the
instance. This happens by default and requires no configuration by the user or
deployer.

Deployer provided data
----------------------

There is however a third type of data. It is possible that the deployer of
OpenStack needs to pass data to an instance. It is also possible that this data
is not known to the user starting the instance. An example might be a
cryptographic token to be used to register the instance with Active Directory
post boot -- the user starting the instance should not have access to Active
Directory to create this token, but the Nova deployment might have permissions
to generate the token on the user's behalf.

Nova supports a mechanism to add "vendordata" to the metadata handed to
instances. This is done by loading named modules, which must appear in the nova
source code. We provide two such modules:

- StaticJSON: a module which can include the contents of a static JSON file
  loaded from disk. This can be used for things which don't change between
  instances, such as the location of the corporate puppet server.

- DynamicJSON: a module which will make a request to an external REST service
  to determine what metadata to add to an instance. This is how we recommend
  you generate things like Active Directory tokens which change per instance.

Tell me more about DynamicJSON
==============================

To use DynamicJSON, you configure it like this:

- Add "DynamicJSON" to the vendordata_providers configuration option. This can
  also include "StaticJSON" if you'd like.
- Specify the REST services to be contacted to generate metadata in the
  vendordata_dynamic_targets configuration option. There can be more than one
  of these, but note that they will be queried once per metadata request from
  the instance, which can mean a fair bit of traffic depending on your
  configuration and the configuration of the instance.

The format for an entry in vendordata_dynamic_targets is like this:

        <name>@<url>

Where name is a short string not including the '@' character, and where the
URL can include a port number if so required. An example would be::

        testing@http://127.0.0.1:125

Metadata fetched from this target will appear in the metadata service at a
new file called vendordata2.json, with a path (either in the metadata service
URL or in the configdrive) like this:

        openstack/2016-10-06/vendor_data2.json

For each dynamic target, there will be an entry in the JSON file named after
that target. For example::

        {
            "testing": {
                "value1": 1,
                "value2": 2,
                "value3": "three"
            }
        }

Do not specify the same name more than once. If you do, we will ignore
subsequent uses of a previously used name.

The following data is passed to your REST service as a JSON encoded POST:

+-------------+-------------------------------------------------+
| Key         | Description                                     |
+=============+=================================================+
| project-id  | The ID of the project that owns this instance.  |
+-------------+-------------------------------------------------+
| instance-id | The UUID of this instance.                      |
+-------------+-------------------------------------------------+
| image-id    | The ID of the image used to boot this instance. |
+-------------+-------------------------------------------------+
| user-data   | As specified by the user at boot time.          |
+-------------+-------------------------------------------------+
| hostname    | The hostname of the instance.                   |
+-------------+-------------------------------------------------+
| metadata    | As specified by the user at boot time.          |
+-------------+-------------------------------------------------+

Deployment considerations
=========================

Nova provides authentication to external metadata services in order to provide
some level of certainty that the request came from nova. This is done by
providing a service token with the request -- you can then just deploy your
metadata service with the keystone authentication WSGI middleware. This is
configured using the keystone authentication parameters in the
``vendordata_dynamic_auth`` configuration group.

References
==========

* Michael Still's talk from the Queens summit in Sydney:
  `Metadata, User Data, Vendor Data, oh my!`_
* Michael's blog post on `deploying a simple vendordata service`_ which
  provides more details and sample code to supplement the documentation above.

.. _Metadata, User Data, Vendor Data, oh my!: https://www.openstack.org/videos/sydney-2017/metadata-user-data-vendor-data-oh-my
.. _deploying a simple vendordata service: http://www.stillhq.com/openstack/000022.html
