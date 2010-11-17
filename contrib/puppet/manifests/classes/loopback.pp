define loopback($num) {
  exec { "mknod -m 0660 /dev/loop${num} b 7 ${num}; chown root:disk /dev/loop${num}":
    creates => "/dev/loop${num}",
    path => ["/usr/bin", "/usr/sbin", "/bin"]
  }
}
