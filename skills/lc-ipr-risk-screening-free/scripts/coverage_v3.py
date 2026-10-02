"""API-first-v3 coverage projection for retrieval discovery versus formal gaps."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

PUBLIC_DISCOVERY_REVISION = 'public-discovery-v1'


def public_discovery_enabled(task):
    return (task.get('retrieval_workflow_revision') == 'api-first-v3'
            and task.get('public_discovery_routing_revision') == PUBLIC_DISCOVERY_REVISION)


def build_requirements(task: dict[str, Any], legacy_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use authorized API routes for v3 recall; retain old official routes as gaps.

    Candidate verification and agent provenance requirements remain untouched.
    Public discovery for provenance rights receives a separate requirement;
    finding a similar image does not prove licensing or source identification.
    Recall rows retain the same requirement identity, while ``routes`` becomes
    the executable discovery set and ``gap_only_routes`` retains the original
    official routes without scheduling redundant browser searches.
    """
    if task.get('retrieval_workflow_revision') != 'api-first-v3':
        return deepcopy(legacy_requirements)
    from common import serper_free_enabled, serpapi_free_enabled, signa_free_enabled
    from provider_routing import priority

    output = []
    public_rights = {'copyright', 'trade_dress', 'unregistered_design'}
    recall_scopes = {(r.get('jurisdiction'), r.get('right_type'))
                     for r in legacy_requirements if r.get('phase') == 'official_recall'}
    for original in legacy_requirements:
        requirement = deepcopy(original)
        if (public_discovery_enabled(task) and requirement.get('phase') == 'provenance'
                and requirement.get('right_type') in public_rights):
            output.append(requirement)
            key = (requirement.get('jurisdiction'), requirement.get('right_type'))
            if key in recall_scopes:
                continue
            recall_scopes.add(key)
            requirement = deepcopy(requirement)
            requirement.update(
                requirement_id='COV-%s-%s-PUBLIC-DISCOVERY' % (key[0], key[1].upper()),
                phase='official_recall', required_for='discovery_only', routes=[])
        if requirement.get('phase') != 'official_recall':
            output.append(requirement)
            continue
        country = str(requirement.get('jurisdiction') or '').upper()
        right = requirement.get('right_type')
        official = deepcopy(requirement.get('routes', []))
        provenance = [deepcopy(route) for route in official if isinstance(route, dict)
                      and route.get('provider') == 'asset_provenance'
                      and route.get('operation') == 'provenance_review'
                      and route.get('method') == 'agent']
        executable = list(provenance)
        for provider, role in priority(country, right, 'discovery', revision='api-first-v3'):
            authorized = (
                provider in {'epo_ops', 'euipo_trademark', 'euipo_design', 'inpi_api'}
                or provider == 'signa' and signa_free_enabled(task)
                or provider.startswith('serper_') and serper_free_enabled(task)
                or provider.startswith('serpapi_') and serpapi_free_enabled(task)
            )
            if not authorized:
                continue
            operation = {
                'epo_ops': 'search', 'inpi_api': 'search', 'euipo_trademark': 'search',
                'euipo_design': 'search', 'signa': 'trademark_search',
                'serpapi_google_patents': 'search', 'serpapi_google_lens': 'image_search',
                'serper_patents': 'patents', 'serper_images': 'images', 'serper_web': 'search',
            }.get(provider)
            if not operation:
                continue
            route = {'provider': provider, 'operation': operation, 'method': 'api',
                     'priority': len(executable) + 1, 'provider_role': role,
                     'required': False}
            if route not in executable:
                executable.append(route)
        for route in official:
            if isinstance(route, dict) and route not in provenance:
                route['gap_only'] = True
        official = [route for route in official if route not in provenance]
        requirement['routes'] = executable
        requirement['fallback_routes'] = [deepcopy(route) for route in executable
            if route.get('provider_role') in {'fallback', 'web_fallback', 'targeted_web_fallback'}]
        requirement['gap_only_routes'] = official
        requirement['expansion_required'] = False
        if right in {'patent', 'utility_model', 'design', 'trademark_word'}:
            requirement['required_axes'] = ['text']
        elif right in {'trademark_figurative', 'copyright', 'trade_dress', 'unregistered_design'}:
            # Visual versus text lanes are selected from current retained product
            # materials at planning time; the canonical scope itself is stable.
            requirement['required_axes'] = []
        else:
            requirement['required_axes'] = []
        requirement['completion_policy'] = 'any'
        requirement['retrieval_workflow_revision'] = 'api-first-v3'
        output.append(requirement)
    # Public enforcement signals are a separate, signal-only discovery lane.
    # Keep it in the plan so a configured web route is actually reachable,
    # without turning those records into an infringement-risk conclusion.
    existing = {(r.get('jurisdiction'), r.get('right_type'), r.get('phase')) for r in output}
    for country in task.get('target_jurisdictions', []):
        country = str(country).upper()
        if (country, 'enforcement', 'official_recall') not in existing:
            routes = []
            for provider, role in priority(country, 'enforcement', 'discovery', revision='api-first-v3'):
                if provider.startswith('serper_') and serper_free_enabled(task):
                    routes.append({'provider': provider, 'operation': 'search', 'method': 'api',
                                   'priority': len(routes) + 1, 'provider_role': role,
                                   'required': False})
                elif provider == 'public_web_browser':
                    routes.append({'provider': provider, 'operation': 'search', 'method': 'targeted_web',
                                   'priority': len(routes) + 1, 'provider_role': role,
                                   'required': False})
            output.append({
                'requirement_id': 'COV-%s-ENFORCEMENT-SIGNALS' % country,
                'jurisdiction': country, 'right_type': 'enforcement',
                'phase': 'official_recall', 'required_for': 'signal_only',
                'completion_policy': 'any', 'required_axes': [],
                'required_language': '', 'expansion_required': False,
                'routes': routes,
                'fallback_routes': [deepcopy(route) for route in routes
                    if route.get('provider_role') in {'fallback', 'web_fallback', 'targeted_web_fallback'}],
                'gap_only_routes': [],
                'retrieval_workflow_revision': 'api-first-v3',
            })
    return output
