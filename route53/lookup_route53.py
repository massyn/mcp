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


def list_registered_domains(profile: str | None = None, filter_str: str | None = None) -> dict:
    """
    List all domains registered in the AWS account via Route53 Domains API,
    enriched with per-domain detail (nameservers, dates, status, DNSSEC, registrar).

    Args:
        profile:    AWS profile name to use (optional, defaults to default profile)
        filter_str: Case-insensitive substring to match against domain names (e.g. '.com', 'acme').
                    Omit to return all domains.

    Returns:
        Dict with 'success' bool and either 'domains' list or 'error' string.
    """
    try:
        if profile:
            session = boto3.Session(profile_name=profile)
            client = session.client('route53domains', region_name='us-east-1')
        else:
            client = boto3.client('route53domains', region_name='us-east-1')

        # Collect summary rows (includes TransferLock, AutoRenew, Expiry)
        summary: dict[str, dict] = {}
        paginator = client.get_paginator('list_domains')
        for page in paginator.paginate():
            for entry in page.get('Domains', []):
                name = entry['DomainName']
                expiry = entry.get('Expiry')
                summary[name] = {
                    'auto_renew': entry.get('AutoRenew'),
                    'transfer_lock': entry.get('TransferLock'),
                    'expiry': expiry.isoformat() if expiry else None,
                }

        # Apply optional filter before fetching per-domain detail
        needle = filter_str.lower() if filter_str else None
        if needle:
            summary = {k: v for k, v in summary.items() if needle in k.lower()}

        # Enrich each domain with detail from get_domain_detail
        domains = []
        for name, base in summary.items():
            try:
                d = client.get_domain_detail(DomainName=name)
                created = d.get('CreatedDate')
                updated = d.get('UpdatedDate')
                expiry = d.get('ExpirationDate')
                domains.append({
                    'domain': name,
                    'expiry': expiry.isoformat() if expiry else base['expiry'],
                    'created': created.isoformat() if created else None,
                    'updated': updated.isoformat() if updated else None,
                    'auto_renew': base['auto_renew'],
                    'transfer_lock': base['transfer_lock'],
                    'name_servers': [ns['Name'] for ns in d.get('Nameservers', [])],
                    'status': d.get('StatusList', []),
                    'dnssec_enabled': bool(d.get('DnssecKeys')),
                    'registrar': d.get('RegistrarName'),
                    'registrar_url': d.get('RegistrarUrl'),
                })
            except ClientError as e:
                domains.append({
                    'domain': name,
                    'expiry': base['expiry'],
                    'auto_renew': base['auto_renew'],
                    'transfer_lock': base['transfer_lock'],
                    'error': f"{e.response['Error']['Code']} - {e.response['Error']['Message']}",
                })

        return {'success': True, 'domains': domains}

    except NoCredentialsError:
        return {'success': False, 'error': 'AWS credentials not configured'}
    except ClientError as e:
        return {'success': False, 'error': f"{e.response['Error']['Code']} - {e.response['Error']['Message']}"}
    except Exception as e:
        return {'success': False, 'error': str(e)}


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
