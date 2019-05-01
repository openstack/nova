Setup multi-cell policy on the controller host. This should not require
a restart of the n-api service (the policy changes should be read
dynamically). The stack user must exist on the controller host first.

**Role Variables**

.. zuul:rolevar:: nova_config_dir
   :default: /etc/nova

   The nova configuration directory.
