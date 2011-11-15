..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration. 
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Nova Quickstart
===============

The quickest way to set up an OpenStack development environment for testing is
to use `DevStack <http://devstack.org/>`_.

Currently, there is no automated way to do a clean reset of DevStack. The
beginnings of an external cleanup script can be found at `Ron Pedde's DevStack
branch <https://github.com/rpedde/devstack/blob/master/clean.sh>`_, which
deletes instances and cleans up security groups.

To manually start over, drop the nova, glance, and keystone databases, delete
the logs, delete the IP addresses and bridges created, and then recreate the
databases and restart the services to get back to a clean state.
