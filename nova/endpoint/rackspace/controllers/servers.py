from nova import rpc
from nova.compute import model as compute
from nova.endpoint.rackspace.controllers.base import BaseController

class ServersController(BaseController):
    entity_name = 'servers'

    def index(cls):
        return [instance_details(inst) for inst in compute.InstanceDirectory().all]

    def show(self, **kwargs):
        instance_id = kwargs['id']
        return compute.InstanceDirectory().get(instance_id)

    def delete(self, **kwargs):
        instance_id = kwargs['id']
        instance = compute.InstanceDirectory().get(instance_id)
        if not instance:
            raise ServerNotFound("The requested server was not found")
        instance.destroy()
        return True

    def create(self, **kwargs):
        inst = self.build_server_instance(kwargs['server'])
        rpc.cast(
            FLAGS.compute_topic, {
                "method": "run_instance",
                "args": {"instance_id": inst.instance_id}})

    def update(self, **kwargs):
        instance_id = kwargs['id']
        instance = compute.InstanceDirectory().get(instance_id)
        if not instance:
            raise ServerNotFound("The requested server was not found")
        instance.update(kwargs['server'])
        instance.save()

    def build_server_instance(self, env):
        """Build instance data structure and save it to the data store."""
        reservation = utils.generate_uid('r')
        ltime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        inst = self.instdir.new()
        inst['name'] = env['server']['name']
        inst['image_id'] = env['server']['imageId']
        inst['instance_type'] = env['server']['flavorId']
        inst['user_id'] = env['user']['id']
        inst['project_id'] = env['project']['id']
        inst['reservation_id'] = reservation
        inst['launch_time'] = ltime
        inst['mac_address'] = utils.generate_mac()
        address = self.network.allocate_ip(
                    inst['user_id'],
                    inst['project_id'],
                    mac=inst['mac_address'])
        inst['private_dns_name'] = str(address)
        inst['bridge_name'] = network.BridgedNetwork.get_network_for_project(
                                inst['user_id'],
                                inst['project_id'],
                                'default')['bridge_name']
        # key_data, key_name, ami_launch_index
        # TODO(todd): key data or root password
        inst.save()
        return inst
