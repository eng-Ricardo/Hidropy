"""Representação Matplotlib dos dados hidráulicos; reutilizável fora do Qt."""

import math
import textwrap

import numpy as np


def draw_message(figure, message):
    figure.clear()
    axes = figure.add_subplot(111)
    axes.set_axis_off()
    axes.text(0.5, 0.5, textwrap.fill(message, 65), ha='center', va='center',
              transform=axes.transAxes, fontsize=11, color='#525b66')
    return axes


def draw_graph(figure, data):
    figure.clear()
    axes = figure.add_subplot(111)
    if data.kind == 'contour':
        from matplotlib.collections import LineCollection
        from matplotlib.patches import Patch
        from matplotlib.tri import Triangulation
        from mpl_toolkits.axes_grid1 import make_axes_locatable

        _, xs, ys, values = zip(*data.points)
        xs, ys, values = np.array(xs), np.array(ys), np.array(values)
        # A triangulação usa coordenadas locais para preservar precisão em UTM.
        local = Triangulation(xs - xs[0], ys - ys[0])
        tri = Triangulation(xs, ys, triangles=local.triangles)
        if np.ptp(values) <= 1e-10:
            axes.tripcolor(tri, values, shading='flat', cmap='viridis',
                           vmin=values[0] - 1, vmax=values[0] + 1)
            axes.legend(handles=[Patch(color='#21918c', label=f'Valor uniforme: {values[0]:g}')])
        else:
            contour = axes.tricontourf(tri, values, levels=12, cmap='viridis')
            color_axes = make_axes_locatable(axes).append_axes('right', size='4%', pad=0.15)
            figure.colorbar(contour, cax=color_axes, label=data.y_label)
        edges = [edge for edge in data.edges if len(edge) >= 2
                 and all(math.isfinite(x) and math.isfinite(y) for x, y in edge)]
        axes.add_collection(LineCollection(edges, colors='#414b57', linewidths=0.7, alpha=0.65))
        axes.scatter(xs, ys, s=12, c='#202833', zorder=3)
        if len(data.points) <= 20:
            for name, x, y, _ in data.points:
                right_edge = x >= max(xs) - 0.1 * max(float(np.ptp(xs)), 1)
                axes.annotate(name, (x, y), xytext=(-4 if right_edge else 4, 4),
                              ha='right' if right_edge else 'left',
                              textcoords='offset points', fontsize=8)
        axes.margins(0.08)
        axes.set_ylabel('Y (m)')
        axes.set_aspect('equal', adjustable='box')
        axes.ticklabel_format(useOffset=False, style='plain')
    else:
        for series in data.series:
            ys = [float('nan') if value is None else value for value in series.y]
            if data.kind == 'frequency':
                axes.step(series.x, ys, where='post', marker='o', label=series.label)
            else:
                axes.plot(series.x, ys, marker='o' if len(ys) <= 50 else None, markersize=3,
                          linewidth=1.7, label=series.label,
                          drawstyle='steps-post' if data.y_label == 'Estado operacional'
                          else 'default')
            if series.labels and series is data.series[0]:
                stride = max(1, math.ceil(len(series.labels) / 20))
                for i in range(0, len(series.labels), stride):
                    if series.y[i] is not None:
                        axes.annotate(series.labels[i], (series.x[i], ys[i]), xytext=(3, 6),
                                      textcoords='offset points', fontsize=8)
        if data.kind == 'frequency':
            axes.set_ylim(0, 105)
        if data.y_label == 'Estado operacional':
            values = sorted({v for s in data.series for v in s.y if v is not None})
            labels = {0: 'Fechado (0)', 1: 'Aberto (1)', 2: 'Ativo (2)'}
            axes.set_yticks(values, [labels.get(v, f'Código {v:g}') for v in values])
        if data.kind in ('time', 'system') and data.series and len(data.series[0].x) == 1:
            axes.set_xticks(data.series[0].x)
        axes.set_ylabel(data.y_label)
        axes.legend(loc='best', fontsize=8)
        axes.grid(True, alpha=0.25)
    axes.set_xlabel(data.x_label)
    axes.set_title(data.title, fontsize=11, pad=12)
    if data.note:
        figure.text(0.02, 0.012, textwrap.fill(data.note, 110), fontsize=8,
                    color='#525b66', va='bottom')
    figure.tight_layout(rect=(0, 0.10 if data.note else 0, 1, 1))
    return axes
