.. _section_manage-compute-users:

====================
Manage Compute users
====================

Access to the Euca2ools (ec2) API is controlled by an access key and a secret
key. The user's access key needs to be included in the request, and the request
must be signed with the secret key. Upon receipt of API requests, Compute
verifies the signature and runs commands on behalf of the user.

To begin using Compute, you must create a user with the Identity service.
