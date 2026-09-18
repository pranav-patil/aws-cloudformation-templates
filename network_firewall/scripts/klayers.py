import urllib.request
import json

python_version = "p3.11"
package = "cryptography"
regions = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2", 
    "eu-central-1", "eu-west-1", "ap-south-1", "ap-southeast-1", 
    "ap-southeast-2", "ap-northeast-1", "ca-central-1", "sa-east-1"
]

print("Mappings:\n  KlayersCryptoMap:")
for region in regions:
    url = f"https://api.klayers.cloud/api/v2/{python_version}/layers/{region}/{package}"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
            # The API returns a list; the last item is the latest layer
            if data and 'arn' in data[-1]:
                print(f"    {region}:\n      Arn: '{data[-1]['arn']}'")
    except Exception as e:
        # Skips silently if a region doesn't support the specific layer yet
        pass