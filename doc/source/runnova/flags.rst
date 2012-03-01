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

Flags and Flagfiles
===================

Nova uses a configuration file containing flags located in
``/etc/nova/nova.conf``. You can get the most recent listing of avaialble
flags by running ``nova-(servicename) --help``, for example:

::

  nova-api --help

A script for generating a sample ``nova.conf`` file is located in
``<nova_root>/tools/conf/run.sh``. This script traverses through the
source code and retrieves information of every option that is
defined. A file named ``nova.conf.sample`` will be placed in the same
directory.

The OpenStack wiki has a page with the flags listed by their purpose
and use at http://wiki.openstack.org/FlagsGrouping.
