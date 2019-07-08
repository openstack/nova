{
    "server" : {
        "adminPass": "MySecretPass",
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "name" : "%(name)s",
        "imageRef" : "%(image_id)s",
        "flavorRef" : "6",
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
        "networks": "auto",
        "host": "openstack-node-01"
    }
}