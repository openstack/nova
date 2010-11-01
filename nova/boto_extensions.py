import base64
import boto
from boto.ec2.connection import EC2Connection

class AjaxConsole:
    def __init__(self, parent=None):
        self.parent = parent
        self.instance_id = None
        self.url = None

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'instanceId':
            self.instance_id = value
        elif name == 'url':
            self.url = value
        else:
            setattr(self, name, value)

class NovaEC2Connection(EC2Connection):
    def get_ajax_console(self, instance_id):
        """
        Retrieves a console connection for the specified instance.

        :type instance_id: string
        :param instance_id: The instance ID of a running instance on the cloud.

        :rtype: :class:`AjaxConsole`
        """
        params = {}
        self.build_list_params(params, [instance_id], 'InstanceId')
        return self.get_object('GetAjaxConsole', params, AjaxConsole)
    pass

def override_connect_ec2(aws_access_key_id=None, aws_secret_access_key=None, **kwargs):
    return NovaEC2Connection(aws_access_key_id, aws_secret_access_key, **kwargs)

boto.connect_ec2 = override_connect_ec2
