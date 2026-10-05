"""Explicit credential-to-apiKey binding; no endpoint or prefix guessing."""
import re


def validate_credential_auth(raw, policy):
    required = {'operation', 'security_scheme', 'token_field', 'prefix', 'headers'}
    if not isinstance(policy, dict) or set(policy) != required:
        raise ValueError('Credential authentication requires an explicit complete policy.')
    operation = policy['operation']
    if not isinstance(operation, str) or not operation.startswith('POST /'):
        raise ValueError('Credential authentication requires a local POST operation.')
    path = operation.split(' ', 1)[1]
    op = raw.get('paths', {}).get(path, {}).get('post')
    scheme = raw.get('components', {}).get('securitySchemes', {}).get(policy['security_scheme'], {})
    if not op or '{' in path or not scheme.get('name') or scheme.get('type') != 'apiKey' or scheme.get('in') != 'header':
        raise ValueError('Credential authentication must bind a documented header apiKey scheme.')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', str(policy['prefix'])):
        raise ValueError('Authentication prefix must be one literal token.')
    if not isinstance(policy['headers'], dict) or any(
        not isinstance(k, str) or not isinstance(v, str) or
        k.lower() in (scheme['name'].lower(), 'content-type', 'cookie') or
        any(c in k + v for c in '\r\n') or '@{' in v
        for k, v in policy['headers'].items()
    ):
        raise ValueError('Authentication headers must contain only static noncredential values.')
    schemas = raw.get('components', {}).get('schemas', {})
    def resolve(node):
        seen = set()
        while '$ref' in node:
            ref = node['$ref']
            if ref in seen or not ref.startswith('#/components/schemas/'):
                raise ValueError('Unsupported authentication schema reference.')
            seen.add(ref)
            node = schemas.get(ref.split('/')[-1], {})
        return node
    request = resolve(op.get('requestBody', {}).get('content', {}).get('application/x-www-form-urlencoded', {}).get('schema', {}))
    if not {'username', 'password'} <= set(request.get('properties', {})) or set(request.get('required', [])) - {'username', 'password'}:
        raise ValueError('Credential form must document username/password without other required fields.')
    response_schemas = [resolve(v.get('content', {}).get('application/json', {}).get('schema', {}))
                        for k, v in op.get('responses', {}).items() if k.isdigit() and 200 <= int(k) < 300]
    if not response_schemas or any(resolve(s.get('properties', {}).get(policy['token_field'], {})).get('type') != 'string' for s in response_schemas):
        raise ValueError('Credential token field must be documented in every successful JSON response.')
    return dict(policy, header=scheme['name'])
