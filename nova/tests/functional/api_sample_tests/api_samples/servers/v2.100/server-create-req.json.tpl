{
    "server" : {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "name" : "new-server-test",
        "imageRef" : "%(image_id)s",
        "flavorRef" : "1",
        "OS-DCF:diskConfig": "AUTO",
        "availability_zone": "%(availability_zone)s",
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
        "hostname": "new-server-test"
    },
    "OS-SCH-HNT:scheduler_hints": {
        "same_host": "48e6a9f6-30af-47e0-bc04-acaed113bb4e"
    }
}
