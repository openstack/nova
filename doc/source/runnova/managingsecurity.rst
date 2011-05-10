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

Security Considerations
=======================

The goal of securing a cloud computing system involves both protecting the instances, data on the instances, and
ensuring users are authenticated for actions and that borders are understood by the users and the system.
Protecting the system from intrusion or attack involves authentication, network protections,  and
compromise detection. 

Key Concepts
------------

Authentication - Each instance is authenticated with a key pair. 

Network - Instances can communicate with each other but you can configure the boundaries through firewall
configuration. 

Monitoring - Log all API commands and audit those logs. 

Encryption - Data transfer between instances is not encrypted. 

