load('ext://cert_manager', 'deploy_cert_manager')
set_team('27d7ad9c-53f8-4700-80b8-b217eeb8effg')

settings = read_yaml('tilt-options.yaml', default={})

if "allowedContexts" in settings:
    allow_k8s_contexts(settings["allowedContexts"])

# min_k8s_version('1.22')
deploy_cert_manager(version="v1.5.3")

# The next 3 lines apply the default Opni YAMLs
local_resource('Opni CRDs',
    'kubectl apply -f https://raw.githubusercontent.com/rancher/opni/main/deploy/manifests/00_crds.yaml')

local_resource('Opni RBAC', 
    'kubectl apply -f https://raw.githubusercontent.com/rancher/opni/rbac-fix/deploy/manifests/01_rbac.yaml')

k8s_custom_deploy('opni', 
    apply_cmd='kubectl apply -f https://raw.githubusercontent.com/rancher/opni/main/deploy/manifests/10_operator.yaml -o yaml',
    delete_cmd='kubectl delete --ignore-not-found -f https://raw.githubusercontent.com/rancher/opni/main/deploy/manifests/10_operator.yaml',
    deps='')



# This will deploy the custom cluster.yaml which only deploys the insights service
k8s_yaml('test/cluster.yaml')
# This tells tilt where to update the image in the cluster yaml
k8s_kind('OpniCluster', api_version='opni.io/v1beta1', image_json_path='{.spec.services.insights.image}')
# This tells tilt to wait for the opni resource.
k8s_resource('cluster', resource_deps=['opni'])


# This will deploy the custom elasticdump pod, and run elasticdump for data setup
local_resource('Elasticdump_Pod_Data', 'kubectl apply -f ')


# Next we tell Tilt to build a custom image for insights with the latest code
docker_build("rancher/opni-insights-service", ".",
    dockerfile='Dockerfile',
    only=["opni-insights-service/app"],
    live_update=[sync('opni-insights-service/app', '/app')])