# -*- mode: ruby -*-
# vi: set ft=ruby :

# VirtualBox is the only supported provider. libvirt/KVM is deliberately not
# used here -- it cannot share AMD-V with VirtualBox on the same host, and the
# other Forail environments are VirtualBox.
ENV["VAGRANT_DEFAULT_PROVIDER"] ||= "virtualbox"

Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
  config.vm.hostname = "awx-build"

  # AWX Dev ports
  config.vm.network "forwarded_port", guest: 8043, host: 8043  # HTTPS
  config.vm.network "forwarded_port", guest: 8013, host: 8013  # HTTP
  config.vm.network "forwarded_port", guest: 8080, host: 8080  # Nginx
  config.vm.network "forwarded_port", guest: 5432, host: 5433  # PostgreSQL

  config.vm.network "private_network", ip: "192.168.56.20"

  config.vm.provider "virtualbox" do |vb|
    vb.name = "awx-build"
    vb.memory = "8192"
    vb.cpus = 4
  end

  # Sync AWX source into VM
  config.vm.synced_folder ".", "/awx_devel", type: "rsync",
    rsync__exclude: [".git/", "node_modules/", "forail/ui/build/", "forail/ui_next/build/", "*.pyc", "__pycache__/"]

  config.vm.provision "shell", path: "tools/scripts/vagrant-provision.sh"
end
