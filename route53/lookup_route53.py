import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def does_domain_exist(domains, profile=None):
    """
    Check if domains are registered or available for registration using AWS Route53 Domains API.

    Args:
        domains: List of domain names to check
        profile: AWS profile name to use (optional, defaults to default profile)

    Returns:
        List of dictionaries with 'domain' and 'result' keys
        result values: 'AVAILABLE', 'UNAVAILABLE', 'RESERVED', 'DONT_KNOW', or error message
    """
    result = []

    try:
        # Initialize boto3 session with specified profile (or default)
        if profile:
            session = boto3.Session(profile_name=profile)
            route53domains = session.client('route53domains', region_name='us-east-1')
        else:
            route53domains = boto3.client('route53domains', region_name='us-east-1')

        # Check each domain
        for domain in domains:
            domain_normalized = domain.strip().lower()

            try:
                # Check domain availability
                response = route53domains.check_domain_availability(DomainName=domain_normalized)

                result.append({
                    'domain': domain,
                    'result': response['Availability']
                })

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_msg = e.response['Error']['Message']

                result.append({
                    'domain': domain,
                    'result': f'error: {error_code} - {error_msg}'
                })

    except NoCredentialsError:
        # No AWS credentials configured
        for domain in domains:
            result.append({
                'domain': domain,
                'result': 'error: AWS credentials not configured'
            })
    except ClientError as e:
        # AWS API error (connection/permission issues)
        error_msg = f"error: {e.response['Error']['Message']}"
        for domain in domains:
            result.append({
                'domain': domain,
                'result': error_msg
            })
    except Exception as e:
        # Other errors
        error_msg = f"error: {str(e)}"
        for domain in domains:
            result.append({
                'domain': domain,
                'result': error_msg
            })

    return result


if __name__ == '__main__':
    # Example 1: Using default AWS profile
    print("Checking domains with default profile:")
    for i in does_domain_exist(['test.com', 'test.other', 'mydomain']):
        print(f"  Domain {i['domain']} status = {i['result']}")

    # Example 2: Using a specific AWS profile
    # Uncomment and replace 'myprofile' with your AWS profile name
    # print("\nChecking domains with specific profile:")
    # for i in does_domain_exist(['example.com'], profile='myprofile'):
    #     print(f"  Domain {i['domain']} status = {i['result']}")
