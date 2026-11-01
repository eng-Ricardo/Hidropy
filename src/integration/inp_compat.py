"""Compatibilidade de dados QEPANET, sem executar nem alterar a rede hidráulica."""

from __future__ import annotations

import math
import re

MARKER = ';@AVANT-QEPANET '
HEADER = re.compile(r'^\s*\[([^\]]+)\]\s*(?:;.*)?$')


def is_extension(name):
    return name.startswith('QEPANET-') or name == 'QOPTIONS'


def split_extensions(text):
    """Comenta extensões e devolve seus blocos originais, incluindo linhas de origem.

    O marcador permite transportar os dados pela pré-verificação e por ferramentas
    EPANET sem reativar seções estrangeiras. A operação é idempotente.
    """
    safe, blocks, current = [], [], None
    for number, raw in enumerate(text.splitlines(), 1):
        carried = raw.startswith(MARKER)
        payload = raw[len(MARKER):] if carried else raw
        match = HEADER.match(payload)
        if match:
            name = match.group(1).strip().upper()
            if is_extension(name):
                current = {'section': name, 'line': number, 'lines': []}
                blocks.append(current)
            elif not carried:
                current = None
        elif current is not None:
            current['lines'].append({'line': number, 'text': payload})
        safe.append(raw if carried or current is None else MARKER + raw)
    return '\n'.join(safe) + '\n', blocks


def reader_text(text):
    """Permite cadastrar POWER 0 para edição, sem modificar o valor importado.

    WNTR exige potência positiva até na leitura. O valor de transporte só existe
    na cópia temporária usada pelo leitor, nunca é simulado e é restaurado antes
    de devolver a rede. Outros erros de sintaxe continuam sendo erros.
    """
    section, lines, zero_pumps = '', [], {}
    for number, raw in enumerate(text.splitlines(), 1):
        match = HEADER.match(raw.split(';', 1)[0])
        if match:
            section = match.group(1).strip().upper()
        data, sep, comment = raw.partition(';')
        tokens = list(re.finditer(r'\S+', data))
        if section == 'PUMPS' and len(tokens) >= 5:
            for index in range(3, len(tokens) - 1, 2):
                if tokens[index].group().upper() != 'POWER':
                    continue
                try:
                    value = float(tokens[index + 1].group())
                except ValueError:
                    continue
                if value == 0:
                    name = tokens[0].group()
                    zero_pumps[name] = {'line': number, 'original': raw}
                    token = tokens[index + 1]
                    data = data[:token.start()] + '1.0' + data[token.end():]
        lines.append(data + (sep + comment if sep else ''))
    return '\n'.join(lines) + '\n', zero_pumps


def _number(value):
    number = float(value.replace(',', '.'))
    if not math.isfinite(number):
        raise ValueError('valor não finito')
    return number


def apply_extensions(net, blocks, length_factor, warnings):
    """Associa metadados por categoria/ID; nunca soma delta Z à cota hidráulica."""
    nodes = {e.name: e for e in net.nodes.values()}
    links = {e.name: e for e in net.links.values()}
    counts = {'materials': 0, 'node_elevations': 0, 'vertex_elevations': 0}
    seen, profiles = set(), {}
    node_kinds = {'QEPANET-JUNCTIONS': 'junction', 'QEPANET-RESERVOIRS': 'reservoir',
                  'QEPANET-TANKS': 'tank'}
    for block in blocks:
        section = block['section']
        if section not in (*node_kinds, 'QEPANET-PIPES', 'QEPANET-VERTICES'):
            if any(row['text'].split(';', 1)[0].strip() for row in block['lines']):
                warnings.append(f'[{section}]: conteúdo guardado no histórico da importação, sem interpretar opções desconhecidas.')
            continue
        for row in block['lines']:
            data = row['text'].split(';', 1)[0].strip()
            if not data:
                continue
            parts = data.split()
            name = parts[0]
            element = (nodes if section in node_kinds else links).get(name)
            expected = node_kinds.get(section, 'pipe' if section == 'QEPANET-PIPES' else None)
            prefix = f"Linha {row['line']} [{section}] '{name}'"
            if element is None or (expected and element.KIND != expected):
                warnings.append(prefix + ': referência ausente ou de outra categoria; registro original preservado no histórico.')
                continue
            meta = element.source_data.setdefault('qepanet', {'original_id': name})
            if section == 'QEPANET-VERTICES':
                try:
                    if len(parts) != 2:
                        raise ValueError('esperada uma cota Z')
                    z = _number(parts[1]) * length_factor
                except ValueError as error:
                    z = None
                    warnings.append(prefix + f': {error}; mantida a posição do vértice sem atribuir cota.')
                profiles.setdefault(element.uid, []).append(z)
                continue
            key = (section, name)
            if key in seen:
                warnings.append(prefix + ': registro duplicado; mantido o primeiro valor válido.')
                continue
            try:
                if section == 'QEPANET-PIPES':
                    material = data.split(None, 1)[1].strip().strip('"')
                    if not material:
                        raise ValueError('material vazio')
                    element.material = material
                    meta['material'] = material
                    counts['materials'] += 1
                else:
                    allowed = (2, 3) if section == 'QEPANET-RESERVOIRS' else (2,)
                    if len(parts) not in allowed:
                        raise ValueError('colunas de cota incompatíveis')
                    delta = _number(parts[1]) * length_factor
                    pressure = _number(parts[2]) * length_factor if len(parts) == 3 else 0.0
                    meta['delta_z'] = delta
                    if element.KIND == 'reservoir':
                        meta['pressure_head'] = pressure
                        element.ground_elevation = element.head - delta - pressure
                    else:
                        element.ground_elevation = element.elevation - delta
                    counts['node_elevations'] += 1
                seen.add(key)
            except (ValueError, IndexError) as error:
                warnings.append(prefix + f': {error}; dado auxiliar não aplicado, original preservado no histórico.')
    for uid, zs in profiles.items():
        link = net.links[uid]
        meta = link.source_data['qepanet']
        if len(zs) != len(link.vertices):
            meta['unmatched_vertex_z'] = zs
            warnings.append(f"'{link.name}': {len(zs)} cotas QEPANET para {len(link.vertices)} vértices XY; "
                            'associação ambígua, perfil não aplicado.')
            continue
        meta['vertex_profile'] = [[float(x), float(y), z] for (x, y), z in zip(link.vertices, zs)]
        counts['vertex_elevations'] += sum(z is not None for z in zs)
    return counts


def annotations(text, net):
    """Preserva descrições e etiquetas EPANET, sem misturar IDs de nós e ligações."""
    stores = {'JUNCTIONS': net.nodes, 'RESERVOIRS': net.nodes, 'TANKS': net.nodes,
              'PIPES': net.links, 'PUMPS': net.links, 'VALVES': net.links}
    by_name = {kind: {e.name: e for e in store.values()} for kind, store in stores.items()}
    node_names = {e.name: e for e in net.nodes.values()}
    link_names = {e.name: e for e in net.links.values()}
    section, archive = '', {}
    for raw in text.splitlines():
        match = HEADER.match(raw.split(';', 1)[0])
        if match:
            section = match.group(1).strip().upper()
            archive.setdefault(section, [])
            continue
        archive.setdefault(section, []).append(raw)
        data, _, comment = raw.partition(';')
        fields = data.split()
        if not fields:
            continue
        if section in by_name:
            e = by_name[section].get(fields[0])
            if e is not None and comment.strip():
                e.notes = comment.strip()
        elif section == 'TAGS' and len(fields) >= 3:
            store = {'NODE': node_names, 'LINK': link_names}.get(fields[0].upper(), {})
            if fields[1] in store:
                store[fields[1]].source_data.setdefault('epanet', {})['tag'] = ' '.join(fields[2:])
    return {section: lines for section, lines in archive.items()
            if section in ('TITLE', 'ENERGY', 'QUALITY', 'SOURCES', 'REACTIONS', 'MIXING',
                           'RULES', 'REPORT', 'LABELS', 'BACKDROP', 'OPTIONS', 'TIMES')}


def export_extensions(net, names):
    """Metadados em comentários: IDs atuais e associação XY/Z verificada."""
    groups = {}
    for node in net.nodes.values():
        meta = node.source_data.get('qepanet', {})
        if 'delta_z' not in meta:
            continue
        section = {'junction': 'QEPANET-JUNCTIONS', 'reservoir': 'QEPANET-RESERVOIRS',
                   'tank': 'QEPANET-TANKS'}[node.KIND]
        if node.KIND == 'reservoir':
            delta = meta['delta_z']
            pressure = node.head - node.ground_elevation - delta if node.ground_elevation is not None else meta.get('pressure_head', 0)
            values = [delta, pressure]
        else:
            values = [node.elevation - node.ground_elevation if node.ground_elevation is not None else meta['delta_z']]
        groups.setdefault(section, []).append(names[node.uid] + '\t' + '\t'.join(format(v, '.17g') for v in values))
    for link in net.links.values():
        if link.KIND == 'pipe' and link.material:
            material = ' '.join(link.material.replace(';', ' ').splitlines())
            groups.setdefault('QEPANET-PIPES', []).append(f'{names[link.uid]}\t{material}')
        profile = link.source_data.get('qepanet', {}).get('vertex_profile', [])
        if len(profile) == len(link.vertices) and all(list(row[:2]) == list(xy) for row, xy in zip(profile, link.vertices)):
            for _, _, z in profile:
                if z is not None:
                    groups.setdefault('QEPANET-VERTICES', []).append(f'{names[link.uid]}\t{z:.17g}')
                else:
                    # Não exporta perfil parcial: a ordem deve continuar inequívoca.
                    groups.setdefault('QEPANET-VERTICES', []).append(f'{names[link.uid]}\tNA')
    return [MARKER + line for section, rows in groups.items() for line in [f'[{section}]', *rows]]
