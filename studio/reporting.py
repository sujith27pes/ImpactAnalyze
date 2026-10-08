"""Human-readable review export, preserving evidence classes and incomplete AI status."""


def jira_review(report):
    ai = report['ai']
    graph = report['graph']
    nodes = {node['id']: node for node in graph['nodes']}

    def source_label(node_id):
        node = nodes.get(node_id)
        if not node:
            return node_id
        repository = node.get('repository') or node.get('module', '')
        return f"{repository} / {node['label']} ({node.get('path', '')}:{node.get('start', 1)})"

    lines = ['Change impact review', report['intent'], '',
             'Snapshot: ' + report['snapshot_id'], 'Gate: ' + report['gate'],
             'AI: ' + ai['status'], 'Tests: selected; not executed']
    if ai.get('message'):
        lines.append('AI details: ' + ai['message'])
    if ai.get('http_status') is not None:
        lines.append('Provider HTTP status: ' + str(ai['http_status']))
    if ai.get('retry_after_seconds'):
        lines.append('Provider cooldown at request time: ' + str(ai['retry_after_seconds']) + ' seconds')
    if ai.get('retry_automatic') is False:
        lines.append('Provider retry: no automatic repeat; submit a new analysis after cooldown')

    lines += ['', 'Affected owners:']
    for handoff in report['handoffs']:
        repository = handoff.get('repository', '')
        label = (repository + ' / ' if repository and repository != handoff['module'] else '') + handoff['module']
        lines.append(f"- {label}: {handoff['owner']}")
    proposal = report.get('counterfactual', {})
    lines += ['', 'Dependency rehearsal:']
    if proposal.get('available'):
        lines.append(f"- In-memory proposal: {proposal['added_count']} relationships added; {proposal['removed_count']} removed")
        lines.append('- Static / declared graph comparison; no code, tests or deployment executed')
    else:
        lines.append('- ' + proposal.get('reason', 'No comparable proposed graph available'))

    lines += ['', 'Contract compatibility alerts:']
    for alert in report.get('contract_alerts', []):
        lines += [f"- {alert['severity']}: {alert['title']}",
                  '  Provider: ' + source_label(alert['source']),
                  '  Consumer: ' + source_label(alert['consumer']),
                  '  Basis: ' + alert['basis'],
                  '  Evidence: ' + ', '.join(alert['evidence'])]
    if not report.get('contract_alerts'):
        lines.append('- No contract alert established in this captured scope; this is not a safety proof')

    lines += ['', 'Source-rule findings:']
    lines += [f"- {f['title']}: {f['explanation']} Evidence {', '.join(f['evidence'])}" for f in report['findings']]
    if not report['findings']:
        lines.append('- No narrow source-rule violation found; review contract alerts and unresolved scope separately')

    if ai.get('analysis'):
        lines += ['', 'AI risk hypotheses (review required):']
        lines += [f"- {r['title']}: {r['explanation']} Evidence {', '.join(r['evidence_ids'])}" for r in ai['analysis']['risks']]
        lines += ['', 'BA clarification questions:'] + ['- ' + q for q in ai['analysis']['ba_questions']]

    lines += ['', 'Selected suites:']
    for test in report['selected_tests']:
        repositories = {graph['evidence'][id].get('repository', '') for id in test.get('evidence', [])
                        if id in graph['evidence']}
        repository = next(iter(repositories)) if len(repositories) == 1 else ''
        lines.append(f"- {test['class']}: {repository + ' / ' if repository else ''}{test['path']}")
    if not report['selected_tests']:
        lines.append('- No linked existing suite found; targeted tests must be reviewed and supplied')

    lines += ['', 'Unresolved scope:', f"- {len(graph.get('unknown', []))} unresolved relationships; {len(graph.get('skipped', []))} skipped entries"]
    lines += ['- ' + limitation for limitation in report.get('limitations', [])]
    lines += ['', 'Evidence:']
    lines += [f"{id}: {e.get('repository', '') + ' / ' if e.get('repository') else ''}{e['path']}:{e['start']}-{e['end']} SHA256 {e['sha256']}"
              for id, e in graph['evidence'].items()]
    return '\n'.join(lines)
