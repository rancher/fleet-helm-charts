## Fleet Agent Helm Chart

Every Fleet managed downstream cluster will run an agent that communicates back to the Fleet manager. This agent is just another set of Kubernetes controllers running in the downstream cluster.

Standalone Fleet users use this chart for agent-based registration. For more details see [agent initiated registration](https://fleet.rancher.io/cluster-registration#agent-initiated).
Fleet in Rancher does not use this chart, but creates the agent deployments programmatically.

The Fleet documentation is centralized in the [doc website](https://fleet.rancher.io/).