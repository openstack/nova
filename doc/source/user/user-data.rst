==============================
Provide user data to instances
==============================

*User data* is a blob of data that the user can specify when they launch an
instance. The instance can access this data through the metadata service or
config drive. Commonly used to pass a shell script that the instance runs on
boot.

For example, one application that uses user data is the
`cloud-init <https://help.ubuntu.com/community/CloudInit>`__ system,
which is an open-source package from Ubuntu that is available on various
Linux distributions and which handles early initialization of a cloud
instance.

You can place user data in a local file and pass it through the
``--user-data <user-data-file>`` parameter at instance creation.

.. code-block:: console

   $ openstack server create --image ubuntu-cloudimage --flavor 1 \
     --user-data mydata.file VM_INSTANCE
