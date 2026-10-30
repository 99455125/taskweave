#!/usr/bin/env python3
"""Rebuild a database into the current schema at a new, explicit destination.

Usage: uv run python scripts/maintain_current_schema.py SOURCE DESTINATION --kind control
The source is read-only. Missing/unknown business columns require a separately
reviewed conversion; this tool never guesses values or alters the source.
"""
import argparse
from copy import deepcopy
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from taskweave.infrastructure.sqlite_storage import (
    current_schema, schema_objects, schema_sql, validate_schema,
)


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def convert_flow(graph):
    """Offline-only structural conversion; business operand values stay intact."""
    graph = deepcopy(graph)
    if isinstance(graph, dict) and set(graph) == {'entry_node_id', 'nodes'}:
        nodes = graph['nodes']
        if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
            raise ValueError('Invalid historical action chain')
        by_id = {node['id']: node for node in nodes}
        if len(by_id) != len(nodes):
            raise ValueError('Duplicate historical action identity')
        current, seen, children = graph['entry_node_id'], set(), []
        while current is not None:
            if current in seen or current not in by_id:
                raise ValueError('Cyclic or incomplete historical action chain')
            node = by_id[current]
            if (set(node) != {'id', 'kind', 'config', 'next'} or node['kind'] != 'action'
                    or node['config'] != {'step_id': current}):
                raise ValueError('Unknown historical action fields require review')
            seen.add(current)
            children.append({'id': current, 'kind': 'action', 'step_id': current})
            current = node['next']
        if seen != set(by_id):
            raise ValueError('Unreachable historical actions require review')
        graph = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': children}}
    if not isinstance(graph, dict) or set(graph) != {'version', 'root'} or graph['version'] != 2:
        raise ValueError('Unknown flow format requires review')

    def node(value):
        kind = value['kind']
        if kind == 'sequence':
            for child in value['children']:
                node(child)
        elif kind == 'if':
            if 'cases' not in value:
                if (not {'id', 'kind', 'condition', 'then', 'else'} <= set(value)
                        or set(value) - {'id', 'kind', 'condition', 'then', 'else', 'outputs'}):
                    raise ValueError('Unknown historical conditional fields require review')
                value['cases'] = [{'id': 'then', 'condition': value.pop('condition'), 'body': value.pop('then')}]
                value['default'] = {'id': 'else', 'body': value.pop('else')}
            for branch in [*value['cases'], value['default']]:
                node(branch['body'])
        elif kind in {'foreach', 'loop'}:
            node(value['body'])
        elif kind != 'action':
            raise ValueError('Unknown flow node requires review')
    node(graph['root'])
    return graph


def convert_cursor(cursor, flow):
    """Move an old selected if body's frames into its explicit current lane."""
    from taskweave.core.flow_machine import _nodes
    nodes = _nodes(flow)

    def convert(value):
        if not isinstance(value, dict) or not {'frames', 'pending'} <= set(value) or not isinstance(value['frames'], list):
            raise ValueError('Unknown recovery cursor requires review')
        result = deepcopy(value)
        frames = result['frames']
        pending = result['pending']
        if pending is not None and (not isinstance(pending, dict) or
                nodes.get(pending.get('node_id'), {}).get('kind') != 'action' or
                nodes[pending['node_id']]['step_id'] != pending.get('step_id')):
            raise ValueError('Unknown recovery action requires review')
        for index, frame in enumerate(frames):
            node = nodes.get(frame.get('node_id'))
            if node is None or node['kind'] != frame.get('kind') or not isinstance(frame.get('path'), str):
                raise ValueError('Unknown recovery frame requires review')
            if frame['kind'] == 'if' and isinstance(frame.get('selected'), str):
                if set(frame) - {'node_id', 'kind', 'path', 'selected'}:
                    raise ValueError('Unknown historical recovery branch fields require review')
                identity = frame['selected']
                bodies = {branch['id']: branch['body'] for branch in [*node['cases'], node['default']]}
                remaining = frames[index + 1:]
                if identity not in bodies or not remaining or remaining[0].get('node_id') != bodies[identity]['id']:
                    raise ValueError('Incomplete historical recovery branch requires review')
                lane = convert({'frames': remaining, 'pending': pending, 'actions': 0, 'control_visits': 0,
                                'resource_path': result.get('resource_path', '/')})
                frame.update(selected=[identity], facts=[], lanes=[lane])
                result['frames'] = frames[:index + 1]
                result['pending'] = None
                break
            if 'lanes' in frame:
                if frame['kind'] != 'if' or not isinstance(frame.get('selected'), list):
                    raise ValueError('Unknown recovery lanes require review')
                frame['lanes'] = [convert(lane) for lane in frame['lanes']]
        return result
    return convert(cursor)


def capture_definition_evidence(db):
    """Capture the repository's exact guard hash and semantic frozen definitions."""
    from taskweave.core.validation import fingerprint, normalize_step
    tasks = {}
    for task_id, schema, graph in db.execute('SELECT task_id,input_schema_json,graph_json FROM tasks'):
        cursor = db.execute('SELECT * FROM steps WHERE task_id=? ORDER BY position', (task_id,))
        names = [column[0] for column in cursor.description]
        steps = []
        for row in cursor:
            step = dict(zip(names, row))
            for key in ('input_schema', 'output_schema', 'bindings', 'capabilities', 'plugin_requirements'):
                step[key] = json.loads(step[key + '_json'])
            steps.append(step)
        pairs = [(step['step_id'], step['content_hash']) for step in steps]
        tasks[task_id] = {
            'hash': fingerprint({'input_schema': schema, 'graph': graph, 'steps': pairs}),
            'semantic': {'task_id': task_id, 'input_schema': json.loads(schema), 'flow': convert_flow(json.loads(graph)),
                         'steps': [(step['step_id'], step['content_hash'], normalize_step(step)) for step in steps]},
        }
    runs = {identity: {'task_id': task, 'hash': digest, 'definition': json.loads(raw) if raw else None}
            for identity, task, digest, raw in db.execute('SELECT run_id,task_id,definition_hash,definition_json FROM task_runs')}
    sequences = {identity: json.loads(raw) for identity, raw in db.execute('SELECT sequence_run_id,snapshot_json FROM sequence_runs')}
    return {'tasks': tasks, 'runs': runs, 'sequences': sequences}


def _frozen_semantic(definition):
    from taskweave.core.validation import normalize_step
    if not isinstance(definition, dict):
        raise ValueError('Missing frozen snapshot prevents hash repair')
    try:
        task = definition['task']
        graph = convert_flow(json.loads(task['graph_json']))
        flow = convert_flow(definition.get('flow', json.loads(task['graph_json'])))
        if graph != flow:
            raise ValueError('Contradictory frozen snapshot flow prevents hash repair')
        return {'task_id': task['task_id'], 'input_schema': json.loads(task['input_schema_json']), 'flow': flow,
                'steps': [(step['step_id'], step['content_hash'], normalize_step(step)) for step in definition['steps']]}
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Incomplete frozen snapshot prevents hash repair') from exc


def repair_definition_hashes(db, evidence, audit):
    """Renew only hashes proven to describe the same task before conversion."""
    from taskweave.core.validation import dumps
    current = capture_definition_evidence(db)
    eligible = {identity: old for identity, old in evidence['tasks'].items()
                if identity in current['tasks'] and old['semantic'] == current['tasks'][identity]['semantic']
                and old['hash'] != current['tasks'][identity]['hash']}
    for run_id, run in current['runs'].items():
        old = eligible.get(run['task_id'])
        if old is None or run['hash'] != old['hash']:
            continue
        prior = evidence['runs'].get(run_id)
        if not prior or prior['task_id'] != run['task_id'] or prior['hash'] != run['hash']:
            audit.append({'kind': 'run_hash_unchanged', 'run_id': run_id, 'reason': 'evidence_identity_mismatch'})
            continue
        # Both the old backup and current frozen definition must attest to the
        # same input contract, step identities/content, and normalized flow.
        if (_frozen_semantic(prior['definition']) != old['semantic'] or
                _frozen_semantic(run['definition']) != old['semantic']):
            raise ValueError(f'Contradictory frozen snapshot for run {run_id}; hash unchanged')
        new_hash = current['tasks'][run['task_id']]['hash']
        db.execute('UPDATE task_runs SET definition_hash=? WHERE run_id=?', (new_hash, run_id))
        audit.append({'kind': 'run_definition_hash', 'run_id': run_id, 'task_id': run['task_id'],
                      'old_hash': run['hash'], 'new_hash': new_hash})
    for identity, snapshot in current['sequences'].items():
        prior = evidence['sequences'].get(identity)
        if prior is None:
            continue
        old_nodes = {node['node_id']: node['task_id'] for node in prior['nodes']}
        changed = False
        for node in snapshot['nodes']:
            task_id, node_id = node['task_id'], node['node_id']
            old = eligible.get(task_id)
            if old is None or snapshot.get('task_hashes', {}).get(node_id) != old['hash']:
                continue
            if old_nodes.get(node_id) != task_id or prior.get('task_hashes', {}).get(node_id) != old['hash']:
                raise ValueError(f'Contradictory sequence snapshot {identity}; hash unchanged')
            new_hash = current['tasks'][task_id]['hash']
            snapshot['task_hashes'][node_id] = new_hash
            changed = True
            audit.append({'kind': 'sequence_task_hash', 'sequence_run_id': identity, 'node_id': node_id,
                          'task_id': task_id, 'old_hash': old['hash'], 'new_hash': new_hash})
        if changed:
            db.execute('UPDATE sequence_runs SET snapshot_json=? WHERE sequence_run_id=?', (dumps(snapshot), identity))


def maintain_control_json(db, *, evidence=None, audit=None):
    """Convert known definitions and renew only proven-equivalent guard hashes."""
    evidence = capture_definition_evidence(db) if evidence is None else evidence
    audit = [] if audit is None else audit
    from taskweave.core.task_flow import validate_flow
    from taskweave.core.sequence_flow import linear_flow, validate_sequence_flow
    from taskweave.core.validation import dumps

    if db.execute('SELECT 1 FROM runtime_lease LIMIT 1').fetchone():
        raise ValueError('An active runtime lease prevents offline maintenance')
    for table, cursor_column in [('task_runs', 'flow_cursor_json'), ('sequence_runs', 'cursor_json')]:
        if db.execute(f"SELECT 1 FROM {table} WHERE status NOT IN ('SUCCEEDED','CANCELLED','FAILED') LIMIT 1").fetchone():
            raise ValueError(f'{table}: active or recoverable runs require explicit resolution')
    if db.execute("SELECT 1 FROM step_attempts WHERE status IN ('RUNNING','UNKNOWN') LIMIT 1").fetchone():
        raise ValueError('An active or recoverable step attempt prevents maintenance')

    def checked_flow(graph, steps):
        result = convert_flow(graph)
        validate_flow(result, steps)
        return result

    for task_id, raw in db.execute('SELECT task_id,graph_json FROM tasks').fetchall():
        steps = [{'step_id': key, 'bindings': json.loads(bindings)} for key, bindings in
                 db.execute('SELECT step_id,bindings_json FROM steps WHERE task_id=?', (task_id,))]
        original = json.loads(raw)
        flow = checked_flow(original, steps)
        if flow != original:
            db.execute("UPDATE tasks SET graph_json=?,flow_validation_state='DRAFT',flow_verified_hash=NULL WHERE task_id=?", (dumps(flow), task_id))

    for run_id, raw, cursor_raw in db.execute('SELECT run_id,definition_json,flow_cursor_json FROM task_runs').fetchall():
        if raw is None:
            if cursor_raw is not None:
                raise ValueError('Historical recovery cursor has no frozen definition')
            continue
        definition = json.loads(raw)
        steps = definition['steps']
        if 'flow' in definition:
            definition['flow'] = checked_flow(definition['flow'], steps)
        elif 'graph_json' in definition.get('task', {}):
            definition['flow'] = checked_flow(json.loads(definition['task']['graph_json']), steps)
        else:
            raise ValueError('Historical run has no frozen flow; reconstruction requires review')
        if 'graph_json' in definition.get('task', {}):
            definition['task']['graph_json'] = dumps(checked_flow(json.loads(definition['task']['graph_json']), steps))
        if definition != json.loads(raw):
            db.execute('UPDATE task_runs SET definition_json=? WHERE run_id=?', (dumps(definition), run_id))
        if cursor_raw is not None:
            cursor = convert_cursor(json.loads(cursor_raw), definition['flow'])
            if cursor != json.loads(cursor_raw):
                db.execute('UPDATE task_runs SET flow_cursor_json=? WHERE run_id=?', (dumps(cursor), run_id))

    for identity, raw, nodes_raw in db.execute('SELECT sequence_id,flow_json,nodes_json FROM task_sequences').fetchall():
        nodes = json.loads(nodes_raw)
        flow = convert_flow(json.loads(raw)) if raw else linear_flow(nodes)
        validate_sequence_flow(flow, nodes)
        if not raw or flow != json.loads(raw):
            db.execute('UPDATE task_sequences SET flow_json=?,revision=revision+1 WHERE sequence_id=?', (dumps(flow), identity))
    for identity, raw, cursor_raw in db.execute('SELECT sequence_run_id,snapshot_json,cursor_json FROM sequence_runs').fetchall():
        snapshot = json.loads(raw)
        flow = convert_flow(snapshot['flow']) if snapshot.get('flow') else linear_flow(snapshot['nodes'])
        validate_sequence_flow(flow, snapshot['nodes'])
        snapshot['flow'] = flow
        if snapshot != json.loads(raw):
            db.execute('UPDATE sequence_runs SET snapshot_json=? WHERE sequence_run_id=?', (dumps(snapshot), identity))
        if cursor_raw is not None:
            cursor = convert_cursor(json.loads(cursor_raw), flow)
            if cursor != json.loads(cursor_raw):
                db.execute('UPDATE sequence_runs SET cursor_json=? WHERE sequence_run_id=?', (dumps(cursor), identity))

    for table in ('flow_instances', 'sequence_instances'):
        for identity, raw in db.execute(f"SELECT rowid,payload_json FROM {table} WHERE kind='if'").fetchall():
            payload = json.loads(raw)
            if isinstance(payload.get('selected'), str):
                if payload['selected'] not in {'then', 'else'}:
                    raise ValueError('Unknown historical selected branch requires review')
                payload['selected'] = [payload['selected']]
                db.execute(f'UPDATE {table} SET payload_json=? WHERE rowid=?', (dumps(payload), identity))

    # Candidates are editable configuration; raw model responses and evidence
    # files remain untouched. Preserve context references and all step documents.
    for identity, raw in db.execute('SELECT generation_id,candidate_json FROM plan_generations WHERE candidate_json IS NOT NULL').fetchall():
        candidate = json.loads(raw)
        if candidate.get('format') not in {'taskweave-task-2', 'taskweave-task-3'}:
            raise ValueError('Unknown candidate package format requires review')
        steps = [{'step_id': entry['key'], 'bindings': entry['document']['bindings']} for entry in candidate['steps']]
        flow = candidate.get('flow', {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
            {'id': step['step_id'], 'kind': 'action', 'step_id': step['step_id']} for step in steps]}})
        candidate['flow'] = checked_flow(flow, steps)
        candidate['format'] = 'taskweave-task-3'
        candidate['flow_validation_state'] = 'DRAFT'
        if candidate != json.loads(raw):
            db.execute('UPDATE plan_generations SET candidate_json=? WHERE generation_id=?', (dumps(candidate), identity))
    repair_definition_hashes(db, evidence, audit)


def rebuild(source, destination, kind, *, definition_evidence=None, audit=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    if not source.is_file():
        raise FileNotFoundError(source)
    evidence = None
    if definition_evidence is not None:
        if kind != 'control':
            raise ValueError('Definition evidence applies only to the control database')
        path = Path(definition_evidence).resolve(strict=True)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as evidence_db, \
                closing(sqlite3.connect(':memory:')) as evidence_snapshot:
            evidence_db.backup(evidence_snapshot)
            evidence = capture_definition_evidence(evidence_snapshot)
    expected = current_schema(kind)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, \
            closing(sqlite3.connect(':memory:')) as snapshot:
        original.backup(snapshot)
        actual = schema_objects(snapshot)
        extra = {key: value for key, value in actual.items() if key not in expected}
        if extra and (kind != 'task-data' or any(
            category not in {'table', 'index'} or not table.startswith('p_')
            for (category, _), (table, _) in extra.items()
        )):
            raise ValueError('Unknown schema objects require a reviewed conversion')
        with tempfile.TemporaryDirectory(prefix='.taskweave-maintenance-', dir=destination.parent) as folder:
            output = Path(folder) / 'current.db'
            with closing(sqlite3.connect(output)) as target:
                target.executescript(schema_sql(kind))
                for (category, _), (_, sql) in extra.items():
                    if category == 'table':
                        target.execute(sql)
                for (category, table), _ in schema_objects(target).items():
                    if category != 'table':
                        continue
                    columns = [r[1] for r in target.execute(f'PRAGMA table_info({quote(table)})')]
                    old_columns = [r[1] for r in snapshot.execute(f'PRAGMA table_info({quote(table)})')]
                    obsolete = {'version'} if table == 'plugin_table_schemas' else set()
                    if not set(columns) <= set(old_columns) or set(old_columns) - set(columns) - obsolete:
                        raise ValueError(f'{table}: business columns differ; reviewed conversion required')
                    names = ','.join(map(quote, columns))
                    rows = snapshot.execute(f'SELECT {names} FROM {quote(table)}')
                    target.executemany(f'INSERT INTO {quote(table)} ({names}) VALUES ({",".join("?" for _ in columns)})', rows)
                for (category, _), (_, sql) in extra.items():
                    if category == 'index':
                        target.execute(sql)
                # Preserve AUTOINCREMENT high-water marks, including deleted rows.
                if snapshot.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                    for table, sequence in snapshot.execute('SELECT name,seq FROM sqlite_sequence'):
                        target.execute('DELETE FROM sqlite_sequence WHERE name=?', (table,))
                        target.execute('INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)', (table, sequence))
                if kind == 'control':
                    maintain_control_json(target, evidence=evidence, audit=audit)
                validate_schema(target, kind)
                if target.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('Foreign key violations; source needs explicit repair')
                if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('Integrity check failed')
                target.commit()
            # Publish without overwriting a destination created during the copy.
            os.link(output, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--kind', choices=('control', 'task-data'), required=True)
    parser.add_argument('--definition-evidence', type=Path)
    args = parser.parse_args()
    audit = []
    result = rebuild(args.source, args.destination, args.kind, definition_evidence=args.definition_evidence, audit=audit)
    print(json.dumps({'destination': str(result), 'definition_hash_updates': audit}))


if __name__ == '__main__':
    main()
