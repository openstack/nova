{
    "server" : {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "name" : "new-server-test",
        "imageRef" : "%(image_id)s",
        "flavorRef" : "http://openstack.example.com/flavors/1",
        "availability_zone": "%(availability_zone)s",
        "OS-DCF:diskConfig": "AUTO",
        "metadata" : {
            "My Server Name" : "Apache1"
        },
        "security_groups": [
            {
                "name": "default"
            }
        ],
        "user_data" : "%(user_data)s",
        "networks": "auto"
    }
}
