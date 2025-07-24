# openbao-manager-go
Golang code for the OpenBao Manager

Manager is a Kubernetes pod or host service that performs the following actions:
* Discover OpenBao servers
* Initialize the OpenBao cluster, raft backend
* Store and retrieve token and shards
* Add/remove OpenBao servers from the raft
* Unseal OpenBao servers

[OpenBao](https://openbao.org/) is an open source, community-driven fork of Vault managed by the Linux Foundation.  OpenBao Manager is a [StarlingX](https://www.starlingx.io/) project.

## Project Status
_Concept and early development_

The openbao-manager-go repo is a pre-alpha status project.  
