# Prefect Docker Deploy

A very opinionated Github Actions workflow to facilitate deployment of Prefect flows into Kubernetes.

Current support:

- Replaces any run config with `KubernetesRun()`
- Replaces any storage with `Docker()`

Roadmap:

- [ ] Replace task result with any cloud-based result (e.g. `S3Result`)
- [ ] Dask cluster support
- [ ] Parameterized Dockerfile path

## Prerequisites for Kubernetes

- Python 3.6 or later (recommended is Python 3.9)
- A fully functioning EKS cluster.
- The Prefect agent pod and its related resources in `prefect-agent.yml` file. Make sure to replace `BASE64_ENCODED_PREFECT__CLOUD__API_KEY`.
- A private ECR repository for the Dockerized Prefect flows
- Make sure to include the used IAM role/user in the ConfigMap `aws-auth` of the EKS cluster. Reference: https://docs.aws.amazon.com/eks/latest/userguide/add-user-role.html
- The Dockerfile should be in the root of the repository. (This will change)


## Prerequisites for Docker
- The executing machine for the BuildKit-run `docker build` command should have Docker installed. This will enable the Prefect to mount the running Docker service and its volume to the multiple registration.

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

## Sample workflow

```yaml
name: Prefect Flows

on:
  push:
    branches: ["main"]

env:
  AWS_DEFAULT_REGION: us-east-2

# Mandatory for IAM AssumeWebIdentity
permissions:
  id-token: write
  contents: write

jobs:
  build-prefect-flows:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v2

      - uses: actions/setup-python@v2
        with:
          python-version: "3.8"

      - name: Configure IAM credentials
        uses: aws-actions/configure-aws-credentials@v1
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
          aws-region: ${{ env.AWS_DEFAULT_REGION }}
          role-duration-seconds: 1200

      - name: Authenticate ECR
        id: authenticate-ecr
        run: |
          account_id=$(aws sts get-caller-identity --query Account --output text)
          ECR_REGISTRY=$account_id.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
          aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REGISTRY
          echo "::set-output name=ECR_REGISTRY::$ECR_REGISTRY"

      ### ---> Insert this workflow
      - name: Deploy Prefect Dockerized flows
        uses: aldwyn/prefect-docker-deploy@main
        env:
          PREFECT__CLOUD__API_KEY: ${{ secrets.PREFECT__CLOUD__API_KEY }}
        with:
          prefect-project-name: ${{ github.repository }}
          create-prefect-project: "true"
          docker-registry-url: ${{ steps.authenticate-ecr.outputs.ECR_REGISTRY }}
          flows-root-directory: .
          dockerfile-path: Dockerfile
```
