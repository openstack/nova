import cloudservers

class IdFake:
    def __init__(self, id):
        self.id = id

# to get your access key:
# from nova.auth import users
# users.UserManger.instance().get_users()[0].access
rscloud = cloudservers.CloudServers(
            'admin',
            '6cca875e-5ab3-4c60-9852-abf5c5c60cc6'
          )
rscloud.client.AUTH_URL = 'http://localhost:8773/v1.0'


rv = rscloud.servers.list()
print "SERVERS: %s" % rv

if len(rv) == 0:
    server = rscloud.servers.create(
               "test-server",
               IdFake("ami-tiny"),
               IdFake("m1.tiny")
             )
    print "LAUNCH: %s" % server
else:
    server = rv[0]
    print "Server to kill: %s" % server

raw_input("press enter key to kill the server")

server.delete()
