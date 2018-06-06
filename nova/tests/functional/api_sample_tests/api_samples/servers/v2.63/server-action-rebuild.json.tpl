{
    "rebuild" : {
        "accessIPv4" : "%(access_ip_v4)s",
        "accessIPv6" : "%(access_ip_v6)s",
        "OS-DCF:diskConfig": "AUTO",
        "imageRef" : "%(uuid)s",
        "name" : "%(name)s",
        "key_name" : "%(key_name)s",
        "description" : "%(description)s",
        "adminPass" : "%(pass)s",
        "metadata" : {
            "meta_var" : "meta_val"
        },
        "user_data": "ZWNobyAiaGVsbG8gd29ybGQi",
        "trusted_image_certificates": [
            "0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8",
            "674736e3-f25c-405c-8362-bbf991e0ce0a"
        ]
    }
}
