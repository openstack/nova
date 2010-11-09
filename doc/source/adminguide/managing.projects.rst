..
      Copyright 2010 United States Government as represented by the
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

Managing Projects
=================

Projects are isolated resource containers forming the principal organizational structure within Nova.  They consist of a separate vlan, volumes, instances, images, keys, and users.

Basic Commands
--------------

Admins and Project Managers can use the 'nova-manage project' command to manage project resources:

* project add: Adds user to project
    * arguments: project user
* project create: Creates a new project
    * arguments: name project_manager [description]
* project delete: Deletes an existing project
    * arguments: project_id
* project environment: Exports environment variables to an sourcable file
    * arguments: project_id user_id [filename='novarc]
* project list: lists all projects
    * arguments: none
* project remove: Removes user from project
    * arguments: project user
* project scrub: Deletes data associated with project
    * arguments: project
* project zipfile: Exports credentials for project to a zip file
    * arguments: project_id user_id [filename='nova.zip]

Setting Quotas
--------------
Nova utilizes a quota system at the project level to control resource consumption across available hardware resources.  Current quota controls are available to limit the:

* Number of volumes which may be created
* Total size of all volumes within a project as measured in GB
* Number of instances which may be launched
* Number of processor cores which may be allocated
* Publicly accessible IP addresses

Use the following command to set quotas for a project 
* project quota: Set or display quotas for project
    * arguments: project_id [key] [value]
