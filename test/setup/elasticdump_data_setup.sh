#!/bin/bash
# Assume Opni is already installed

set -e

# Install elasticdump pod
kubectl apply -f $(dirname $0)/elasticdump.yaml -n opni-system


# Obtain opni-es-password
kubectl get secret -n opni-system opni-es-password -o json | jq '.data | map_values(@base64d)' > es-password.json
sed -i -e '3d' es-password.json
sed -i -e '1d' es-password.json
sed -i -e 's/  "password": "//g' es-password.json
sed -i -e 's/"//g' es-password.json
echo "Password saved."


# Run elasticdump command to dump data into elasticsearch
kubectl exec -it -n opni-system elasticdump-bash -- /bin/bash -c "ls tmp && \
echo $es_password && \
NODE_TLS_REJECT_UNAUTHORIZED=0 elasticdump --noRefresh --fileSize=1gb --retryAttempts 10 --retryDelay 2500 \
--fsCompress --limit 10000 --input=https://admin:$es_password@opni-es-client.opni.svc.cluster.local:9200/logs \
--output "example.json" --type=data"

rm es-password.json
unset es_password