{
    "server" : {
        "name" : "device-tagging-server",
        "flavorRef" : "%(host)s/flavors/1",
        "networks" : [{
            "uuid" : "3cb9bc59-5699-4588-a4b1-b87f96708bc6",
            "tag": "nic1"
        }],
        "block_device_mapping_v2": [{
            "uuid": "%(image_id)s",
            "source_type": "image",
            "destination_type": "volume",
            "boot_index": 0,
            "volume_size": "1",
            "tag": "disk1"
        }]
    }
}
