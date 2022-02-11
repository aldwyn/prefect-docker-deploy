# Prefect Docker Deploy

A very opinionated Github Actions workflow to facilitate deployment Prefect flows into Kubernetes.

Current support:

- `KubernetesRun()` as the run config
- `Docker()` as the storage

Roadmap:

- [ ] Add support for other storages
- [ ] Convert task result to any cloud-based result (e.g. `S3Result`)

## Prerequisites for Kubernetes

- Python 3.6 or later (recommended is Python 3.9)
- A fully functioning EKS cluster.
- The Prefect agent pod and its related resources in `prefect-agent.yml` file. Make sure to replace `BASE64_ENCODED_PREFECT__CLOUD__API_KEY`.
- A private ECR repository for the Dockerized Prefect flows
- Make sure to include the used IAM role/user in the ConfigMap `aws-auth` of the EKS cluster. Reference: https://docs.aws.amazon.com/eks/latest/userguide/add-user-role.html

  ```bash
  kubectl get configmap aws-auth -n kube-system -o yaml
  ```

  The `aws-auth` ConfigMap must now look like the following:

  ```yaml
  apiVersion: v1
  data:
    ...
    mapUsers: |
      - "rolearn": "arn:aws:iam::<AWS_ACCT_ID>:role/github-actions-service-account-role"
        "username": "github-actions-service-account-role"
        "groups":
        - "system:masters"
  kind: ConfigMap
  ```
