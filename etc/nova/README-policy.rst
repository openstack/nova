Currently nova support policy.d directory. The default policy rules can be
overrided by add file into policy.d and the files in the policy.d are loaded
by alphabetical order.

There are some default policy file at here:

* etc/nova/policy.json: includes the common and legacy policy rules. Those
legacy rules are used by EC2 and Nova V2 API.
* etc/nova/policy.d/00-os-compute-api.json: only includes the policy rules
for Nova V2.1 API.
