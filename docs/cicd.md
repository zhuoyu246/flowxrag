# CI/CD

`deploy/jenkins/Jenkinsfile` targets a Jenkins agent with Docker, Go, Python,
and kubectl installed. Gitea is a webhook and Git source in production; it is
not started by local Compose.

```text
Gitea push -> Jenkins -> Go CI + Python CI -> Docker build -> Harbor push
           -> kubectl rolling update -> rollout status -> rollback on failure
```

`dev` selects `rag-staging`; `main` selects `rag-production`. Registry and
cluster credentials are Jenkins credentials (`harbor-registry`,
`kubeconfig-rag`), not source code. Images are tagged with a short Git commit,
never just `latest`.
