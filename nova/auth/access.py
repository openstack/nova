# Copyright [2010] [Anso Labs, LLC]
# 
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
# 
#        http://www.apache.org/licenses/LICENSE-2.0
# 
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Simple base set of RBAC rules which map API endpoints to LDAP groups.
For testing accounts, users will always have PM privileges.
"""


# This is logically a RuleSet or some such.
    
def allow_describe_images(user, project, target_object):
    return True
    
def allow_describe_instances(user, project, target_object):
    return True

def allow_describe_addresses(user, project, target_object):
    return True

def allow_run_instances(user, project, target_object):
    # target_object is a reservation, not an instance
    # it needs to include count, type, image, etc.
    
    # First, is the project allowed to use this image
    
    # Second, is this user allowed to launch within this project
    
    # Third, is the count or type within project quota
    
    return True
    
def allow_terminate_instances(user, project, target_object):
    # In a project, the PMs and Sysadmins can terminate
    return True
    
def allow_get_console_output(user, project, target_object):
    # If the user launched the instance, 
    # Or is a sysadmin in the project, 
    return True

def allow_allocate_address(user, project, target_object):
    # There's no security concern in allocation, 
    # but it can get expensive. Limit to PM and NE.
    return True

def allow_associate_address(user, project, target_object):
    # project NE only
    # In future, will perform a CloudAudit scan first
    # (Pass / Fail gate)
    return True

def allow_register(user, project, target_object):
    return False

def is_allowed(action, user, project, target_object):
    return globals()['allow_%s' % action](user, project, target_object)

