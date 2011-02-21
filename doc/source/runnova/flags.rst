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

Nova uses a configuration file containing flags located in /etc/nova/nova.conf. You can get the most recent listing of avaialble flags by running nova-(servicename) --help, for example, nova-api --help. 

Here's a list of available flags and their default settings. 

  --ajax_console_proxy_port: port that ajax_console_proxy binds
    (default: '8000')
  --ajax_console_proxy_topic: the topic ajax proxy nodes listen on
    (default: 'ajax_proxy')
  --ajax_console_proxy_url: location of ajax console proxy, in the form
    "http://127.0.0.1:8000"
    (default: 'http://127.0.0.1:8000')
  --auth_token_ttl: Seconds for auth tokens to linger
    (default: '3600')
    (an integer)
  --aws_access_key_id: AWS Access ID
    (default: 'admin')
  --aws_secret_access_key: AWS Access Key
    (default: 'admin')
  --compute_manager: Manager for compute
    (default: 'nova.compute.manager.ComputeManager')
  --compute_topic: the topic compute nodes listen on
    (default: 'compute')
  --connection_type: libvirt, xenapi or fake
    (default: 'libvirt')
  --console_manager: Manager for console proxy
    (default: 'nova.console.manager.ConsoleProxyManager')
  --console_topic: the topic console proxy nodes listen on
    (default: 'console')
  --control_exchange: the main exchange to connect to
    (default: 'nova')
  --db_backend: The backend to use for db
    (default: 'sqlalchemy')
  --default_image: default image to use, testing only
    (default: 'ami-11111')
  --default_instance_type: default instance type to use, testing only
    (default: 'm1.small')
  --default_log_levels: list of logger=LEVEL pairs
    (default: 'amqplib=WARN,sqlalchemy=WARN,eventlet.wsgi.server=WARN')
    (a comma separated list)
  --default_project: default project for openstack
    (default: 'openstack')
  --ec2_dmz_host: internal ip of api server
    (default: '$my_ip')
  --ec2_host: ip of api server
    (default: '$my_ip')
  --ec2_path: suffix for ec2
    (default: '/services/Cloud')
  --ec2_port: cloud controller port
    (default: '8773')
    (an integer)
  --ec2_scheme: prefix for ec2
    (default: 'http')
  --[no]enable_new_services: Services to be added to the available pool on
    create
    (default: 'true')
  --[no]fake_network: should we use fake network devices and addresses
    (default: 'false')
  --[no]fake_rabbit: use a fake rabbit
    (default: 'false')
  --glance_host: glance host
    (default: '$my_ip')
  --glance_port: glance port
    (default: '9292')
    (an integer)
  -?,--[no]help: show this help
  --[no]helpshort: show usage only for this module
  --[no]helpxml: like --help, but generates XML output
  --host: name of this node
    (default: 'osdemo03')
  --image_service: The service to use for retrieving and searching for images.
    (default: 'nova.image.s3.S3ImageService')
  --instance_name_template: Template string to be used to generate instance
    names
    (default: 'instance-%08x')
  --logfile: output to named file
  --logging_context_format_string: format string to use for log messages with
    context
    (default: '%(asctime)s %(levelname)s %(name)s [%(request_id)s %(user)s
    %(project)s] %(message)s')
  --logging_debug_format_suffix: data to append to log format when level is
    DEBUG
    (default: 'from %(processName)s (pid=%(process)d) %(funcName)s
    %(pathname)s:%(lineno)d')
  --logging_default_format_string: format string to use for log messages without
    context
    (default: '%(asctime)s %(levelname)s %(name)s [-] %(message)s')
  --logging_exception_prefix: prefix each line of exception output with this
    format
    (default: '(%(name)s): TRACE: ')
  --my_ip: host ip address
    (default: '184.106.73.68')
  --network_manager: Manager for network
    (default: 'nova.network.manager.VlanManager')
  --network_topic: the topic network nodes listen on
    (default: 'network')
  --node_availability_zone: availability zone of this node
    (default: 'nova')
  --null_kernel: kernel image that indicates not to use a kernel, but to use a
    raw disk image instead
    (default: 'nokernel')
  --osapi_host: ip of api server
    (default: '$my_ip')
  --osapi_path: suffix for openstack
    (default: '/v1.0/')
  --osapi_port: OpenStack API port
    (default: '8774')
    (an integer)
  --osapi_scheme: prefix for openstack
    (default: 'http')
  --periodic_interval: seconds between running periodic tasks
    (default: '60')
    (a positive integer)
  --pidfile: pidfile to use for this service
  --rabbit_host: rabbit host
    (default: 'localhost')
  --rabbit_max_retries: rabbit connection attempts
    (default: '12')
    (an integer)
  --rabbit_password: rabbit password
    (default: 'guest')
  --rabbit_port: rabbit port
    (default: '5672')
    (an integer)
  --rabbit_retry_interval: rabbit connection retry interval
    (default: '10')
    (an integer)
  --rabbit_userid: rabbit userid
    (default: 'guest')
  --rabbit_virtual_host: rabbit virtual host
    (default: '/')
  --region_list: list of region=fqdn pairs separated by commas
    (default: '')
    (a comma separated list)
  --report_interval: seconds between nodes reporting state to datastore
    (default: '10')
    (a positive integer)
  --s3_dmz: s3 dmz ip (for instances)
    (default: '$my_ip')
  --s3_host: s3 host (for infrastructure)
    (default: '$my_ip')
  --s3_port: s3 port
    (default: '3333')
    (an integer)
  --scheduler_manager: Manager for scheduler
    (default: 'nova.scheduler.manager.SchedulerManager')
  --scheduler_topic: the topic scheduler nodes listen on
    (default: 'scheduler')
  --sql_connection: connection string for sql database
    (default: 'sqlite:///$state_path/nova.sqlite')
  --sql_idle_timeout: timeout for idle sql database connections
    (default: '3600')
  --sql_max_retries: sql connection attempts
    (default: '12')
    (an integer)
  --sql_retry_interval: sql connection retry interval
    (default: '10')
    (an integer)
  --state_path: Top-level directory for maintaining nova's state
    (default: '/usr/lib/pymodules/python2.6/nova/../')
  --[no]use_syslog: output to syslog
    (default: 'false')
  --[no]verbose: show debug output
    (default: 'false')
  --volume_manager: Manager for volume
    (default: 'nova.volume.manager.VolumeManager')
  --volume_name_template: Template string to be used to generate instance names
    (default: 'volume-%08x')
  --volume_topic: the topic volume nodes listen on
    (default: 'volume')
  --vpn_image_id: AMI for cloudpipe vpn server
    (default: 'ami-cloudpipe')
  --vpn_key_suffix: Suffix to add to project name for vpn key and secgroups
    (default: '-vpn')