# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Methods for API calls to control instances via AMQP.
"""


from nova import db
from nova import flags
from nova import rpc

FLAGS = flags.FLAGS


def reboot(instance_id, context=None):
    """Reboot the given instance.

    #TODO(gundlach) not actually sure what context is used for by ec2 here
    -- I think we can just remove it and use None all the time.
    """
    instance_ref = db.instance_get_by_ec2_id(context, instance_id)
    host = instance_ref['host']
    rpc.cast(context,
             db.queue_get_for(context, FLAGS.compute_topic, host),
             {"method": "reboot_instance",
              "args": {"instance_id": instance_ref['id']}})
