{
    "server" : {
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
        "name" : "%(name)s",
        "imageRef" : "%(image_id)s",
        "flavorRef" : "6",
        "availability_zone": "nova",
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
        "trusted_image_certificates": [
            "0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8",
            "674736e3-f25c-405c-8362-bbf991e0ce0a"
        ]
    },
    "OS-SCH-HNT:scheduler_hints": {
        "same_host": "%(uuid)s"
    }
}
