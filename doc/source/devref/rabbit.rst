..
      Copyright (c) 2010 Citrix Systems, Inc.
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

RabbitMQ and Nova
=================

RabbitMQ is the messaging component chosen by the OpenStack cloud.  RabbitMQ sits between any two Nova components and allows them to communicate in a loosely coupled fashion. More precisely, Nova components (the compute fabric of OpenStack) use Remote Procedure Calls (RPC hereinafter) to communicate to one another; however such a paradigm is built atop the publish/subscribe paradigm so that the following benefits can be achieved:

    * Decoupling between client and servant (such as the client does not need to know where the servant's reference is).
    * Full a-synchronism between client and servant (such as the client does not need the servant to run at the same time of the remote call).
    * Random balancing of remote calls (such as if more servants are up and running, one-way calls are transparently dispatched to the first available servant).

Nova (Austin release) uses both direct and topic-based exchanges. The architecture looks like the one depicted in the figure below:

.. image:: /images/rabbit/arch.png
   :width: 60%

..

Nova implements RPC (both request+response, and one-way, respectively nicknamed 'rpc.call' and 'rpc.cast') over AMQP by providing an adapter class which take cares of marshaling and unmarshaling of messages into function calls. Each Nova service (for example Compute, Volume, etc.) create two queues at the initialization time, one which accepts messages with routing keys 'NODE-TYPE.NODE-ID' (for example compute.hostname) and another, which accepts messages with routing keys as generic 'NODE-TYPE' (for example compute). The former is used specifically when Nova-API needs to redirect commands to a specific node like 'euca-terminate instance'. In this case, only the  compute node whose host's hypervisor is running the virtual machine can kill the instance. The API acts as a consumer when RPC calls are request/response, otherwise is acts as publisher only. 

Nova RPC Mappings
-----------------

The figure below shows the internals of a RabbitMQ node when a single instance is deployed and shared in an OpenStack cloud. Every Nova component connects to the RabbitMQ instance and, depending on its personality (for example a compute node or a network node), may use the queue either as an Invoker (such as API or Scheduler) or a Worker (such as Compute, Volume or Network). Invokers and Workers do not actually exist in the Nova object model, but we are going to use them as an abstraction for sake of clarity. An Invoker is a component that sends messages in the queuing system via two operations: 1) rpc.call and ii) rpc.cast; a Worker is a component that receives messages from the queuing system and reply accordingly to rcp.call operations. 

Figure 2 shows the following internal elements:

    * Topic Publisher: a Topic Publisher comes to life when an rpc.call or an rpc.cast operation is executed; this object is instantiated and used to push a message to the queuing system. Every publisher connects always to the same topic-based exchange; its life-cycle is limited to the message delivery.
    * Direct Consumer: a Direct Consumer comes to life if (an only if) a rpc.call operation is executed; this object is instantiated and used to receive a response message from the queuing system; Every consumer connects to a unique direct-based exchange via a unique exclusive queue; its life-cycle is limited to the message delivery; the exchange and queue identifiers are determined by a UUID generator, and are marshaled in the message sent by the Topic Publisher (only rpc.call operations).
    * Topic Consumer: a Topic Consumer comes to life as soon as a Worker is instantiated and exists throughout its life-cycle; this object is used to receive messages from the queue and it invokes the appropriate action as defined by the Worker role. A Topic Consumer connects to the same topic-based exchange either via a shared queue or via a unique exclusive queue. Every Worker has two topic consumers, one that is addressed only during rpc.cast operations (and it connects to a shared queue whose exchange key is 'topic') and the other that is addressed only during rpc.call operations (and it connects to a unique queue whose exchange key is 'topic.host').
    * Direct Publisher: a Direct Publisher comes to life only during rpc.call operations and it is instantiated to return the message required by the request/response operation. The object connects to a direct-based exchange whose identity is dictated by the incoming message.
    * Topic Exchange: The Exchange is a routing table that exists in the context of a virtual host (the multi-tenancy mechanism provided by RabbitMQ); its type (such as topic vs. direct) determines the routing policy; a RabbitMQ node will have only one topic-based exchange for every topic in Nova.
    * Direct Exchange: this is a routing table that is created during rpc.call operations; there are many instances of this kind of exchange throughout the life-cycle of a RabbitMQ node, one for each rpc.call invoked.
    * Queue Element: A Queue is a message bucket. Messages are kept in the queue until a Consumer (either Topic or Direct Consumer) connects to the queue and fetch it. Queues can be shared or can be exclusive. Queues whose routing key is 'topic' are shared amongst Workers of the same personality.

.. image:: /images/rabbit/rabt.png
   :width: 60%

..

RPC Calls
---------

The diagram below shows the message flow during an rp.call operation: 

    1. a Topic Publisher is instantiated to send the message request to the queuing system; immediately before the publishing operation, a Direct Consumer is instantiated to wait for the response message.
    2. once the message is dispatched by the exchange, it is fetched by the Topic Consumer dictated by the routing key (such as 'topic.host') and passed to the Worker in charge of the task.
    3. once the task is completed, a Direct Publisher is allocated to send the response message to the queuing system.
    4. once the message is dispatched by the exchange, it is fetched by the Direct Consumer dictated by the routing key (such as 'msg_id') and passed to the Invoker.

.. image:: /images/rabbit/flow1.png
   :width: 60%

..

RPC Casts
---------

The diagram below the message flow during an rp.cast operation: 

    1. A Topic Publisher is instantiated to send the message request to the queuing system.
    2. Once the message is dispatched by the exchange, it is fetched by the Topic Consumer dictated by the routing key (such as 'topic') and passed to the Worker in charge of the task.

.. image:: /images/rabbit/flow2.png
   :width: 60%

..

RabbitMQ Load
-------------

At any given time the load of a RabbitMQ node is function of the following parameters:

    * Throughput of API calls: the number of API calls (more precisely rpc.call ops) being served by the OpenStack cloud dictates the number of direct-based exchanges, related queues and direct consumers connected to them.
    * Number of Workers: there is one queue shared amongst workers with the same personality; however there are as many exclusive queues as the number of workers; the number of workers dictates also the number of routing keys within the topic-based exchange, which is shared amongst all workers.

The figure below shows the status of the RabbitMQ node after Nova components' bootstrap in a test environment. Exchanges and queues being created by Nova components are: 

    * Exchanges
       1. nova (topic exchange)
    * Queues
       1. compute.phantom (phantom is hostname)
       2. compute 
       3. network.phantom (phantom is hostname)
       4. network
       5. volume.phantom (phantom is hostname)
       6. volume
       7. scheduler.phantom (phantom is hostname)
       8. scheduler
    
.. image:: /images/rabbit/state.png
   :width: 60%

..

RabbitMQ Gotchas
----------------

Nova uses Carrot to connect to the RabbitMQ environment. Carrot is a Python library that in turn uses AMQPLib, a library that implements the standard AMQP 0.8 at the time of writing. When using Carrot, Invokers and Workers need the following parameters in order to instantiate a Connection object that connects to the RabbitMQ server (please note that most of the following material can be also found in the Carrot documentation; it has been summarized and revised here for sake of clarity):

    * Hostname: The hostname to the AMQP server.
    * Userid: A valid username used to authenticate to the server.
    * Password: The password used to authenticate to the server.
    * Virtual_host: The name of the virtual host to work with. This virtual host must exist on the server, and the user must have access to it. Default is "/".
    * Port: The port of the AMQP server. Default is 5672 (amqp).

The following parameters are default:

    * Insist: insist on connecting to a server. In a configuration with multiple load-sharing servers, the Insist option tells the server that the client is insisting on a connection to the specified server. Default is False.
    * Connect_timeout: the timeout in seconds before the client gives up connecting to the server. The default is no timeout.
    * SSL: use SSL to connect to the server. The default is False.

More precisely Consumers need the following parameters:

    * Connection: the above mentioned Connection object.
    * Queue: name of the queue.
    * Exchange: name of the exchange the queue binds to.
    * Routing_key: the interpretation of the routing key depends on the value of the exchange_type attribute.
    
      * Direct exchange: if the routing key property of the message and the routing_key attribute of the queue are identical, then the message is forwarded to the queue.
      * Fanout exchange: messages are forwarded to the queues bound the exchange, even if the binding does not have a key.
      * Topic exchange: if the routing key property of the message matches the routing key of the key according to a primitive pattern matching scheme, then the message is forwarded to the queue. The message routing key then consists of words separated by dots (".", like domain names), and two special characters are available; star ("") and hash ("#"). The star matches any word, and the hash matches zero or more words. For example ".stock.#" matches the routing keys "usd.stock" and "eur.stock.db" but not "stock.nasdaq".
      
    * Durable: this flag determines the durability of both exchanges and queues; durable exchanges and queues remain active when a RabbitMQ server restarts. Non-durable exchanges/queues (transient exchanges/queues) are purged when a server restarts. It is worth noting that AMQP specifies that durable queues cannot bind to transient exchanges. Default is True.
    * Auto_delete: if set, the exchange is deleted when all queues have finished using it. Default is False.
    * Exclusive: exclusive queues (such as non-shared) may only be consumed from by the current connection. When exclusive is on, this also implies auto_delete. Default is False.
    * Exchange_type: AMQP defines several default exchange types (routing algorithms) that covers most of the common messaging use cases.
    * Auto_ack: acknowledgement is handled automatically once messages are received. By default auto_ack is set to False, and the receiver is required to manually handle acknowledgment.
    * No_ack: it disable acknowledgement on the server-side. This is different from auto_ack in that acknowledgement is turned off altogether. This functionality increases performance but at the cost of reliability. Messages can get lost if a client dies before it can deliver them to the application.
    * Auto_declare: if this is True and the exchange name is set, the exchange will be automatically declared at instantiation. Auto declare is on by default.
      Publishers specify most the parameters of Consumers (such as they do not specify a queue name), but they can also specify the following:
    * Delivery_mode: the default delivery mode used for messages. The value is an integer. The following delivery modes are supported by RabbitMQ:
    
          * 1 or "transient": the message is transient. Which means it is stored in memory only, and is lost if the server dies or restarts.
          * 2 or "persistent": the message is persistent. Which means the message is stored both in-memory, and on disk, and therefore preserved if the server dies or restarts.

The default value is 2 (persistent). During a send operation, Publishers can override the delivery mode of messages so that, for example, transient messages can be sent over a durable queue.
